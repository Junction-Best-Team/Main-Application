"""Authored harness regressions; providers, catalog and clock are synthetic."""

import json
import time
from copy import deepcopy
from threading import Barrier, Event, Lock

import pytest
import test_agent as fixtures
from test_agent import (  # noqa: F401 -- shared fixtures and authored transcript helpers
    HISTORY,
    FakeService,
    call,
    meal,
    product,
    purchase,
    reply,
    scripted,
)

from aimo import agent
from aimo.agent_provider import AssistantReply
from aimo.agent_reads import MAX_PARALLEL_READS, executions
from aimo.agent_tools import ToolSession
from aimo.chat_schemas import MealPlan
from aimo.db import Problem
from aimo.schemas import ProductSummary

config = fixtures.config
identity = fixtures.identity
database = fixtures.database
reset_buyers = fixtures.reset_buyers


def calls(*ids):
    return AssistantReply.model_validate(
        reply(*[call("get_product", {"product_id": p}) for p in ids])
    ).tool_calls


def test_reads_overlap_but_merge_and_reply_in_model_order(monkeypatch, config, identity):
    service = FakeService(identity)
    barrier = Barrier(2)
    second_finished = Event()

    def read(_, pid):
        barrier.wait(timeout=2)  # Serial execution fails rather than silently passing.
        if pid == "pasta":
            assert second_finished.wait(2)
        else:
            second_finished.set()
        return product(pid)

    service.get_product = read
    seen = scripted(
        monkeypatch,
        [
            reply(*[call("get_product", {"product_id": p}) for p in ("pasta", "eggs")]),
            reply(text="Done."),
        ],
    )
    events = []
    agent.run_turn(identity, HISTORY, service, on_progress=events.append)
    outputs = [
        json.loads(m["content"])["result"]["id"]
        for m in seen[-1]["messages"]
        if m["role"] == "tool"
    ]
    assert outputs == ["pasta", "eggs"]
    assert [e.kind for e in events[:6]] == [
        "started",
        "thinking",
        "tool_started",
        "tool_started",
        "tool_completed",
        "tool_completed",
    ]
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))


def test_parallelism_is_bounded_and_children_do_not_mutate_parent(identity):
    service = FakeService(identity)
    session = ToolSession(identity, service)
    barrier = Barrier(MAX_PARALLEL_READS)
    lock = Lock()
    active = 0
    peak = 0

    def read(_, pid):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=2)
        # The live cache is changed only when the runner consumes finished results.
        assert pid not in session.products
        with lock:
            active -= 1
        return product(pid)

    service.get_product = read
    ids = [f"p{i}" for i in range(MAX_PARALLEL_READS * 2)]
    result = list(
        executions(
            session,
            calls(*ids),
            time.monotonic() + 5,
            lambda: None,
            agent.Progress(identity["_turn_id"], None),
            max_errors=4,
            round_number=1,
        )
    )
    assert all(error is None for _, _, error in result)
    assert list(session.products) == ids
    assert peak == MAX_PARALLEL_READS


def test_plan_and_prepare_are_barriers_between_read_groups(monkeypatch, config, identity):
    service = FakeService(identity)
    seen = scripted(
        monkeypatch,
        [
            reply(
                *[
                    call("get_product", {"product_id": p})
                    for p in ("pasta", "eggs", "pork", "cheese", "pepper")
                ],
                call("publish_meal_plan", meal()),
                call("prepare_order", purchase()),
                call("get_purchase_policy"),
            ),
            reply(text="Review the basket."),
        ],
    )
    result = agent.run_turn(identity, HISTORY, service)
    assert result.proposal_id == service.saved["proposal_id"]
    assert [c[0] for c in service.calls][-2:] == ["prepare", "policy"]
    assert len([m for m in seen[-1]["messages"] if m["role"] == "tool"]) == 8


def test_failed_parallel_read_is_isolated_and_never_cached(identity):
    service = FakeService(identity)
    session = ToolSession(identity, service)
    original = service.get_product

    def read(who, pid):
        if pid == "bad":
            raise Problem("NOT_FOUND", "Missing.", 404)
        return original(who, pid)

    service.get_product = read
    outcomes = list(
        executions(
            session,
            calls("bad", "good"),
            time.monotonic() + 5,
            lambda: None,
            agent.Progress(identity["_turn_id"], None),
            max_errors=4,
            round_number=2,
        )
    )
    assert outcomes[0][2].code == "NOT_FOUND"
    assert outcomes[1][2] is None
    assert list(session.products) == ["good"]


@pytest.mark.parametrize("ids", [("a",), ("a", "b")])
def test_late_reads_cannot_write_session_or_start_plan_changes(identity, ids):
    service = FakeService(identity)
    session = ToolSession(identity, service)
    release = Event()
    finished = Barrier(len(ids) + 1)

    def read(_, pid):
        assert release.wait(2)
        finished.wait(timeout=2)
        return product(pid)

    service.get_product = read
    pending = executions(
        session,
        calls(*ids),
        time.monotonic() + 0.05,
        lambda: None,
        agent.Progress(identity["_turn_id"], None),
        max_errors=4,
        round_number=1,
    )
    try:
        _, _, error = next(pending)
        assert error.code == "LLM_TIMEOUT"
    finally:
        pending.close()
        release.set()
        finished.wait(timeout=2)
    assert session.products == {} and session.plan is None


def test_cancelled_reads_are_fenced_before_merging(identity):
    service = FakeService(identity)
    session = ToolSession(identity, service)
    cancelled = Event()

    def read(_, pid):
        cancelled.set()
        return product(pid)

    def live():
        if cancelled.is_set():
            raise Problem("TURN_REPLACED", "Cancelled.")

    service.get_product = read
    with pytest.raises(Problem) as error:
        list(
            executions(
                session,
                calls("a", "b"),
                time.monotonic() + 5,
                live,
                agent.Progress(identity["_turn_id"], None),
                max_errors=4,
                round_number=1,
            )
        )
    assert error.value.code == "TURN_REPLACED"
    assert session.products == {}


def test_search_inspects_shortlist_once_and_keeps_candidates_unselected(identity):
    service = FakeService(identity)
    ids = ["pasta", "eggs", "pork", "cheese"]
    service.search_products = lambda *_: {
        "products": [
            {k: product(p)[k] for k in ProductSummary.model_fields}
            | {"score": 0.9, "match_is_suitability_proof": False}
            for p in ids
        ],
        "generation": "fixture",
        "model": "fixture",
        "strategy": "hybrid",
        "note": "Authored candidates.",
    }
    session = ToolSession(identity, service)
    first = session.invoke("search_products", '{"query":"carbonara"}')
    assert set(session.products) == set(ids[:3])
    assert "descriptions" in first["products"][0]
    assert "descriptions" not in first["products"][3]
    assert all(p["match_is_suitability_proof"] is False for p in first["products"])
    assert session.invoke("search_products", '{"query":"carbonara"}') == first
    session.invoke("get_product", '{"product_id":"pasta"}')
    assert len(service.calls) == 3
    assert session.plan is None and session.proposal is None


@pytest.mark.parametrize("code", ["LLM_TIMEOUT", "LLM_UNAVAILABLE"])
def test_reviewed_partial_plan_survives_provider_failure(monkeypatch, config, identity, code):
    scripted(
        monkeypatch,
        [reply(call("publish_meal_plan", meal(False))), Problem(code, "private failure", 503)],
    )
    result = agent.run_turn(identity, HISTORY, FakeService(identity))
    assert result.meal_plan == MealPlan.model_validate(meal(False))
    assert result.proposal_id is None
    assert "progress is saved" in result.text
    assert ("time limit" in result.text) is (code == "LLM_TIMEOUT")
    assert "private failure" not in result.text


def test_matched_plan_timeout_reports_only_unfinished_basket_checks(monkeypatch, config, identity):
    scripted(
        monkeypatch,
        [
            reply(
                *[
                    call("get_product", {"product_id": p})
                    for p in ("pasta", "eggs", "pork", "cheese", "pepper")
                ]
            ),
            reply(call("publish_meal_plan", meal())),
            Problem("LLM_TIMEOUT", "synthetic timeout", 504),
        ],
    )
    result = agent.run_turn(identity, HISTORY, FakeService(identity))
    assert result.meal_plan is not None and result.proposal_id is None
    assert "ingredients have catalog selections" in result.text
    assert "remaining basket checks" in result.text
    assert "still need catalog matches" not in result.text


@pytest.mark.parametrize("blocker", ["quantity", "form", "evidence"])
def test_one_recipe_gap_does_not_stop_other_ingredient_matching(
    monkeypatch, config, identity, blocker
):
    plan_id = "6f1c1d2e-5b7a-4c3d-9a1e-0b2c3d4e5f60"
    plan = meal(False) | {"recipe_plan_id": plan_id, "recipe_plan_revision": 2}
    for item in plan["ingredients"]:
        item.update(ingredient_id=item["name"], status="unresolved", form="raw")
    blocked = plan["ingredients"][-1]
    if blocker == "quantity":
        blocked.update(amount=None, reason="This ingredient needs a reviewed scaling rule.")
    elif blocker == "form":
        blocked["form"] = "unspecified"
    else:
        blocked["reason"] = "No current reviewed evidence that this product fits the ingredient and form."
    original_blocked = deepcopy(blocked)
    service = FakeService(identity)
    service.get_recipe_plan = lambda *_: deepcopy(plan)

    def match(*_):
        plan["ingredients"][0].update(
            product_id="pasta", status="matched", purchase_amount="20", purchase_unit="KG"
        )
        plan["recipe_plan_revision"] += 1
        return deepcopy(plan)

    service.match_ingredient = match
    seen = scripted(monkeypatch, [
        reply(call("get_recipe_plan", {"plan_id": plan_id})),
        reply(call("get_product", {"product_id": "pasta"})),
        reply(call("match_ingredient", {"plan_id": plan_id, "revision": 2,
                                       "ingredient_id": "pasta", "product_id": "pasta"})),
        reply(text="I matched the pasta. The pepper still needs a quantity for this recipe."),
    ])
    result = agent.run_turn(identity, HISTORY, service)
    assert len(seen) == 4
    assert result.meal_plan.ingredients[0].status == "matched"
    assert result.meal_plan.ingredients[-1] == MealPlan.model_validate(plan).ingredients[-1]
    assert plan["ingredients"][-1] == original_blocked
    assert "I matched the pasta" in result.text
    assert "More product searches" not in result.text
    assert result.proposal_id is None
    assert not any(c[0] in ("policy", "prepare") for c in service.calls)


def test_duplicate_reads_share_work_and_keep_log_context(identity, caplog):
    import logging

    service = FakeService(identity)
    session = ToolSession(identity, service)
    with caplog.at_level(logging.INFO):
        outcomes = list(
            executions(
                session,
                calls("pasta", "pasta"),
                time.monotonic() + 5,
                lambda: None,
                agent.Progress(identity["_turn_id"], None),
                max_errors=4,
                round_number=3,
            )
        )
    assert len(outcomes) == 2 and all(error is None for _, _, error in outcomes)
    assert len(service.calls) == 1
    rows = [json.loads(r.message) for r in caplog.records if r.name == "aimo.operations"]
    invoked = [r for r in rows if r["event"] == "tool.call.started"]
    assert len(invoked) == 1 and invoked[0]["round"] == 3
    assert "private-provider-key" not in caplog.text
