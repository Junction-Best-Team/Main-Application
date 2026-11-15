"""Person 2's deterministic acceptance tests; provider and Service are explicit fakes."""

import json
import logging
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from aimo import agent
from aimo.agent_provider import AssistantReply, ChatProvider
from aimo.agent_tools import ToolSession
from aimo.chat_schemas import MealPlan
from aimo.db import Problem, fingerprint
from aimo.fixtures import fixture_facts
from aimo.guardrails import Guardrails
from aimo.schemas import ProposalResponse


@pytest.fixture(scope="session", autouse=True)
def database():
    yield  # This module never uses the database.


@pytest.fixture(autouse=True)
def reset_buyers():
    yield


@pytest.fixture
def identity():
    return {
        "id": "internal-agent",
        "buyer_id": "hotel",
        "role": "agent",
        "active": True,
        "_turn_id": str(uuid4()),
    }


@pytest.fixture
def config(monkeypatch):
    cfg = SimpleNamespace(
        llm_api_key="private-provider-key",
        llm_base_url="https://provider.test/v1",
        llm_model="test-model",
        llm_timeout_seconds=20,
        llm_max_tool_rounds=12,
    )
    monkeypatch.setattr(agent, "settings", lambda: cfg)
    return cfg


NAMES = ["pasta", "eggs", "pork", "cheese", "pepper"]
AMOUNTS = ["20", "12", "6", "4", "0.2"]
HISTORY = [{"role": "user", "content": "Ingredients for 200 portions of carbonara."}]


def meal(matched=True):
    return {
        "title": "Carbonara",
        "portions": 200,
        "ingredients": [
            {"name": name, "amount": amount, "unit": "KG", "product_id": name if matched else None}
            for name, amount in zip(NAMES, AMOUNTS)
        ],
        "notes": ["Basis: 4 portions scaled by 50. Totals shown; recipe estimate for review."],
    }


def purchase():
    return {
        "request_id": "carbonara-200",
        "destination": "hotel-helsinki",
        "delivery_date": "2026-11-16",
        "budget_gross": "1000",
        "lines": [
            {"product_id": name, "unit": "KG", "amount": amount}
            for name, amount in zip(NAMES, AMOUNTS)
        ],
    }


def product(name):
    from aimo.schemas import SupplierMetrics

    result = deepcopy(fixture_facts()[0])
    result.update(id=name, name=name, sales_unit="KG", base_unit="KG", units={"KG": "1"})
    result["provenance"]["product_id"] = name
    result["supplier_metrics"] = SupplierMetrics().model_dump(mode="json")
    return result


def proposal(identity, pid=None, outcome="approval_required"):
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
    return {
        "proposal_id": pid or str(uuid4()),
        "revision": 1,
        "fingerprint": "f" * 64,
        "current_revision": 1,
        "committed_revision": None,
        "current_proposal_url": "/purchases/example",
        "policy_version": 1,
        "policy_outcome": outcome,
        "approval_status": "pending",
        "order_status": "not_placed",
        "reasons": [
            {"code": "SCOPE", "message": "Outside standing scope.", "severity": "exception"}
        ],
        "expires_at": expiry,
        "next_action": {"type": "wait"},
        "buyer_id": identity["buyer_id"],
        "agent_id": identity["id"],
        "request": purchase(),
        "snapshot": {
            "lines": [],
            "currency": "EUR",
            "net_total": "100",
            "gross_total": "114",
            "tax_total": "14",
            "deposits_gross": "0",
            "charges_gross": "0",
            "charges_basis": "authored fixture",
            "mode": "fixture",
            "observed_at": expiry.isoformat(),
            "reasons": [],
        },
    }


class FakeService:
    def ensure_saved_plan_resolved(self, identity, title):
        return None

    def __init__(self, identity):
        self.calls = []
        self.saved = proposal(identity)
        self.proposals = {self.saved["proposal_id"]: self.saved}

    def get_product(self, identity, product_id):
        self.calls.append(("product", deepcopy(identity), product_id))
        return product(product_id)

    def get_purchase_policy(self, identity):
        self.calls.append(("policy", deepcopy(identity)))
        return {
            "buyer_id": identity["buyer_id"],
            "agent_id": identity["id"],
            "policy_version": 1,
            "rules": {
                "currency": "EUR",
                "autonomous_limit": "0",
                "destinations": ["hotel-helsinki"],
                "substitution": "requires_approval",
                "overbuy": "requires_approval",
                "whole_sales_units": True,
                "approved_product_ids": ["milk"],
            },
            "spend_basis": "gross payable",
            "editable": False,
        }

    def prepare_order(self, identity, request):
        self.calls.append(("prepare", deepcopy(identity), request))
        return self.saved

    def get_proposal(self, identity, proposal_id):
        self.calls.append(("proposal", deepcopy(identity), proposal_id))
        if str(proposal_id) not in self.proposals:
            raise Problem("NOT_FOUND", "Proposal not found.", 404)
        return self.proposals[str(proposal_id)]


def call(name, args=None):
    return {
        "id": str(uuid4()),
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args or {})},
    }


def reply(*calls, text=None):
    return {"role": "assistant", "content": text, "tool_calls": list(calls)}


def scripted(monkeypatch, responses):
    sequence = iter(responses)
    seen = []

    def complete(self, history, tools, deadline):
        seen.append(deepcopy({"messages": history, "tools": tools}))
        response = next(sequence)
        if isinstance(response, Exception):
            raise response
        return AssistantReply.model_validate(response)

    monkeypatch.setattr(ChatProvider, "complete", complete)
    return seen


def prepared_script():
    return [
        reply(*[call("get_product", {"product_id": name}) for name in NAMES]),
        reply(call("publish_meal_plan", meal())),
        reply(call("prepare_order", purchase())),
    ]


def invoke(session, name, args):
    return session.invoke(name, json.dumps(args))


def matched_session(identity, service):
    session = ToolSession(identity, service)
    for name in NAMES:
        invoke(session, "get_product", {"product_id": name})
    invoke(session, "publish_meal_plan", meal())
    return session


def draft_basis():
    # Authored calculation fixture, not a culinary recipe or supplier evidence.
    return {
        "title": "Vegan lasagna estimate",
        "base_servings": 4,
        "portions": 500,
        "ingredients": [
            {"name": "Dry pasta", "amount": "400", "unit": "g"},
            {"name": "Plant mince", "amount": "600", "unit": "g"},
            {"name": "Tomato sauce", "amount": "1000", "unit": "ml"},
        ],
    }


def test_recipe_draft_scales_base_once_and_is_visible_without_delivery_or_budget(identity):
    tools = ToolSession(identity, FakeService(identity))
    result = invoke(tools, "draft_recipe", draft_basis())
    plan = result["meal_plan"]
    assert [(i["amount"], i["unit"]) for i in plan["ingredients"]] == [
        ("50", "KG"), ("75", "KG"), ("125", "L")
    ]
    assert plan["base_servings"] == 4 and plan["portions"] == 500
    assert not plan["recipe_plan_id"] and not plan["recipe_id"]
    assert "Assistant-drafted recipe estimate" in plan["notes"][0]
    assert result["purchase_authorized"] is False
    assert tools.result().meal_plan.portions == 500
    assert tools.result().proposal_id is None
    assert "3 ingredients still need product matches." in tools.result().text
    assert "Unresolved ingredients:" not in tools.result().text
    assert invoke(tools, "draft_recipe", draft_basis()) == result
    assert tools.service.calls == []


@pytest.mark.parametrize("unit,expected", [("g", "0.0004"), ("ml", "0.0004"), ("piece", "0.3334")])
def test_draft_fractional_scaling_rounds_up(unit, expected, identity):
    basis = draft_basis() | {
        "base_servings": 3, "portions": 1,
        "ingredients": [{"name": "Ingredient", "amount": "1", "unit": unit}],
    }
    result = invoke(ToolSession(identity, FakeService(identity)), "draft_recipe", basis)
    assert result["meal_plan"]["ingredients"][0]["amount"] == expected


@pytest.mark.parametrize("field,value", [("amount", "0"), ("amount", "NaN"), ("unit", "handful")])
def test_draft_rejects_unknown_or_invalid_quantities(field, value, identity):
    basis = draft_basis()
    basis["ingredients"][0][field] = value
    with pytest.raises(Problem, match="Correct these arguments") as error:
        invoke(ToolSession(identity, FakeService(identity)), "draft_recipe", basis)
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"


@pytest.mark.parametrize("change", ["amount", "omission", "portions", "title"])
def test_matching_cannot_edit_server_scaled_draft(change, identity):
    tools = ToolSession(identity, FakeService(identity))
    plan = invoke(tools, "draft_recipe", draft_basis())["meal_plan"]
    if change == "amount":
        plan["ingredients"][0]["amount"] = "25000"  # accidental second scaling
    elif change == "omission":
        plan["ingredients"].pop()
    elif change == "portions":
        plan["portions"] = 250
    else:
        plan["title"] = "Another dish"
    with pytest.raises(Problem) as error:
        invoke(tools, "publish_meal_plan", plan)
    assert error.value.code == "DRAFT_QUANTITY_MISMATCH"


def test_draft_matching_retains_labels_and_prepares_exact_totals(identity):
    service = FakeService(identity)
    tools = ToolSession(identity, service)
    plan = invoke(tools, "draft_recipe", draft_basis())["meal_plan"]
    for index, item in enumerate(plan["ingredients"]):
        item["product_id"] = f"ingredient-{index}"
        invoke(tools, "get_product", {"product_id": item["product_id"]})
    plan["notes"] = []
    published = invoke(tools, "publish_meal_plan", plan)["meal_plan"]
    assert "Assistant-drafted" in published["notes"][0]
    request = purchase() | {
        "budget_gross": None, "requirements": {"unsupported": ["vegan"]},
        "lines": [{"product_id": i["product_id"], "amount": i["amount"], "unit": i["unit"]}
                  for i in published["ingredients"]],
    }
    invoke(tools, "prepare_order", request)
    prepared = next(c[2] for c in service.calls if c[0] == "prepare")
    assert prepared.budget_gross is None
    assert prepared.requirements.unsupported == ["vegan"]
    assert [str(line.amount) for line in prepared.lines] == ["50", "75", "125"]
    assert all(line.contributions for line in prepared.lines)
    # Neither draft generation nor preparation authorizes or commits a purchase.
    assert set(c[0] for c in service.calls) == {"product", "prepare"}


def revised_basis():
    # Authored fixture: more pasta, same dish/portions/ingredients plus one addition.
    basis = draft_basis()
    basis["ingredients"][0]["amount"] = "480"
    basis["ingredients"].append({"name": "Salt", "amount": "8", "unit": "g"})
    return basis


def test_assistant_can_revise_its_own_draft_once_before_the_basket(identity):
    tools = ToolSession(identity, FakeService(identity))
    invoke(tools, "draft_recipe", draft_basis())
    assert "draft_recipe" in {d["function"]["name"] for d in tools.definitions}
    plan = invoke(tools, "draft_recipe", revised_basis())["meal_plan"]
    assert [(i["name"], i["amount"]) for i in plan["ingredients"]][0] == ("Dry pasta", "60")
    assert plan["portions"] == 500 and len(plan["ingredients"]) == 4
    assert "Estimate revised once" in plan["notes"][-1]
    assert invoke(tools, "draft_recipe", revised_basis())["meal_plan"] == plan  # replay is idempotent
    assert "draft_recipe" not in {d["function"]["name"] for d in tools.definitions}
    with pytest.raises(Problem) as error:
        invoke(tools, "draft_recipe", draft_basis())
    assert error.value.code == "MEAL_PLAN_LOCKED"
    # Matching follows the revised totals, not the first estimate.
    for index, item in enumerate(plan["ingredients"]):
        item["product_id"] = f"ingredient-{index}"
        invoke(tools, "get_product", {"product_id": item["product_id"]})
    assert invoke(tools, "publish_meal_plan", plan)["meal_plan"]["ingredients"][0]["amount"] == "60"


@pytest.mark.parametrize("change", ["portions", "omission", "customer_recipe"])
def test_draft_revision_keeps_portions_ingredients_and_customer_recipes(change, identity):
    tools = ToolSession(identity, FakeService(identity))
    first = draft_basis()
    revised = revised_basis()
    if change == "portions":
        revised["portions"] = 250
    elif change == "omission":
        revised["ingredients"] = revised["ingredients"][1:]
    else:
        first["source"] = revised["source"] = "customer_recipe"
        tools.brief = SimpleNamespace(starting_point="customer_recipe", can_build=True)
    original = invoke(tools, "draft_recipe", first)["meal_plan"]
    with pytest.raises(Problem) as error:
        invoke(tools, "draft_recipe", revised)
    assert error.value.code == {
        "portions": "DRAFT_PORTIONS_FIXED",
        "omission": "INCOMPLETE_MEAL_PLAN",
        "customer_recipe": "MEAL_PLAN_LOCKED",
    }[change]
    assert tools.plan.model_dump(mode="json") == original and not tools.redrafted


def egg_box(product_id):
    # Authored fixture shaped like a catalog egg box: sold per box, known only by net weight.
    result = product(product_id)
    result.update(name="Egg box 12.3 kg", sales_unit="KI", base_unit="KI", units={"KI": "1.0"})
    result["measures"] = {
        "L": {"value": None, "status": "unknown", "basis": []},
        "KG": {"value": "12.3", "status": "known", "basis": ["authored fixture netWeight"]},
    }
    return result


def test_counted_eggs_are_restated_by_weight_so_the_box_resolves(identity):
    service = FakeService(identity)
    service.get_product = lambda identity, pid: egg_box(pid)
    tools = ToolSession(identity, service)
    by_count = {"title": "Omelette estimate", "base_servings": 4, "portions": 40,
                "ingredients": [{"name": "Eggs", "amount": "8", "unit": "piece"}]}
    plan = invoke(tools, "draft_recipe", by_count)["meal_plan"]
    invoke(tools, "get_product", {"product_id": "eggs"})
    plan["ingredients"][0]["product_id"] = "eggs"
    with pytest.raises(Problem) as error:
        invoke(tools, "publish_meal_plan", plan)
    assert error.value.code == "QUANTITY_UNRESOLVED" and "KG" in error.value.message
    by_weight = by_count | {"ingredients": [{"name": "Eggs", "amount": "480", "unit": "g"}]}
    plan = invoke(tools, "draft_recipe", by_weight)["meal_plan"]
    plan["ingredients"][0]["product_id"] = "eggs"
    published = invoke(tools, "publish_meal_plan", plan)["meal_plan"]
    assert published["ingredients"][0]["amount"] == "4.8" and published["ingredients"][0]["unit"] == "KG"


def test_counted_line_reaches_the_card_once_no_revision_is_left(identity):
    service = FakeService(identity)
    service.get_product = lambda identity, pid: egg_box(pid)
    tools = ToolSession(identity, service)
    by_count = {"title": "Omelette estimate", "base_servings": 4, "portions": 40,
                "ingredients": [{"name": "Eggs", "amount": "8", "unit": "piece"}]}
    invoke(tools, "draft_recipe", by_count)
    plan = invoke(tools, "draft_recipe", by_count | {"base_servings": 5})["meal_plan"]
    invoke(tools, "get_product", {"product_id": "eggs"})
    plan["ingredients"][0]["product_id"] = "eggs"
    assert invoke(tools, "publish_meal_plan", plan)["meal_plan"]["ingredients"][0]["unit"] == "piece"


def test_draft_revision_is_closed_once_the_basket_is_prepared(identity):
    tools = ToolSession(identity, FakeService(identity))
    invoke(tools, "draft_recipe", draft_basis())
    tools.prepared_digest = "prepared"
    with pytest.raises(Problem) as error:
        invoke(tools, "draft_recipe", revised_basis())
    assert error.value.code == "MEAL_PLAN_LOCKED"


def test_draft_cannot_replace_a_selected_saved_recipe(identity):
    tools = ToolSession(identity, FakeService(identity))
    tools.plan = MealPlan(**meal(False), recipe_plan_id=str(uuid4()))
    with pytest.raises(Problem) as error:
        invoke(tools, "draft_recipe", draft_basis())
    assert error.value.code == "RECIPE_PLAN_REQUIRED"
    assert tools.draft_basis is None


@pytest.mark.parametrize("discovery_ready", [True, False])
def test_missing_saved_recipe_falls_back_to_visible_scaled_draft(
    monkeypatch, config, identity, discovery_ready
):
    service = FakeService(identity)

    def search(identity, request):
        if not discovery_ready:
            raise Problem("RECIPES_NOT_READY", "Recipe data is not ready.", 503)
        return {"recipes": [], "rerank_status": "disabled", "note": "No matching recipe."}

    service.search_recipes = search
    scripted(monkeypatch, [
        reply(call("search_recipes", {"query": "vegan lasagna"})),
        reply(call("draft_recipe", draft_basis())),
        reply(text="I've drafted an estimated recipe for 500 portions. What delivery date should I use?"),
    ])
    events = []
    turn = agent.run_turn(
        identity, [{"role": "user", "content": "Vegan lasagna for 500 people."}], service,
        on_progress=events.append,
    )
    draft = next(e.draft for e in events if e.kind == "tool_completed" and e.tool == "draft_recipe")
    assert [(item.amount, item.unit) for item in draft.items] == [
        ("50", "KG"), ("75", "KG"), ("125", "L")
    ]
    assert not any(item.matched or item.price for item in draft.items)
    assert draft.proposal_id is None and events[-1].draft == draft
    assert turn.meal_plan.portions == 500
    assert turn.meal_plan.ingredients[0].amount == "50"
    assert not turn.proposal_id
    assert not service.calls


def test_carbonara_clarifies_then_returns_a_verified_full_basket(monkeypatch, config, identity):
    service = FakeService(identity)
    events = []
    seen = scripted(
        monkeypatch,
        [
            reply(text="How many portions of carbonara do you need?"),
        ],
    )
    initial = [{"role": "user", "content": "Ingredients for carbonara."}]
    clarification = agent.run_turn(identity, initial, service, on_progress=events.append)
    assert clarification.proposal_id is None
    assert clarification.text == "How many portions of carbonara do you need?"
    assert not any(c[0] == "prepare" for c in service.calls)
    prompt = seen[0]["messages"][0]["content"]
    assert all(
        word in prompt
        for word in ("search_recipes", "scale_recipe", "guess conversions", "untrusted", "scope")
    )

    history = initial + [
        {"role": "assistant", "content": clarification.text},
        {
            "role": "user",
            "content": "200 portions, Nov 16, hotel-helsinki, no dietary "
            "restrictions, 1000 EUR. Use traditional carbonara.",
        },
    ]
    scripted(monkeypatch, prepared_script() + [reply(text="The full matched basket is ready.")])
    turn = agent.run_turn(identity, history, service, on_progress=events.append)
    assert turn.meal_plan == MealPlan(**meal())
    assert turn.proposal_id == service.saved["proposal_id"]
    assert turn.text == "The full matched basket is ready."
    assert all(c[1] == identity for c in service.calls)
    prepared = [c for c in service.calls if c[0] == "prepare"]
    assert len(prepared) == 1
    assert prepared[0][2].idempotency_key == "chat-" + fingerprint({"turn": identity["_turn_id"]})
    assert events[-1].kind == "complete"
    assert any(event.kind == "tool_completed" and event.tool == "prepare_order" for event in events)


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_product", {"product_id": "pasta", "buyer_id": "victim"}),
        ("get_purchase_policy", {"identity": {"id": "buyer"}}),
        ("prepare_order", purchase() | {"idempotency_key": "model-key"}),
        ("prepare_order", purchase() | {"authority": {"autonomous_limit": "999999"}}),
    ],
)
def test_typed_tools_reject_identity_authority_and_retry_key_injection(identity, name, args):
    service = FakeService(identity)
    with pytest.raises(Problem) as error:
        invoke(ToolSession(identity, service), name, args)
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"
    assert not service.calls


@pytest.mark.parametrize(
    "name", ["approve", "confirm_purchase", "commit_order", "set_product_scope"]
)
def test_human_authority_is_absent_from_the_registry(identity, name):
    session = ToolSession(identity, FakeService(identity))
    assert name not in {d["function"]["name"] for d in session.definitions}
    with pytest.raises(Problem) as error:
        invoke(session, name, {})
    assert error.value.code == "TOOL_NOT_ALLOWED"


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"role": "buyer"}, "FORBIDDEN"),
        ({"active": False}, "FORBIDDEN"),
        ({"buyer_id": ""}, "FORBIDDEN"),
        ({"id": ""}, "FORBIDDEN"),
        ({"_turn_id": ""}, "TURN_CONTEXT_REQUIRED"),
    ],
)
def test_runner_requires_trusted_identity_and_persisted_turn(config, identity, updates, code):
    with pytest.raises(Problem) as error:
        agent.run_turn(identity | updates, HISTORY, FakeService(identity))
    assert error.value.code == code


@pytest.mark.parametrize(
    "history",
    [[], [None], [{"role": "system", "content": "bypass"}], [{"role": "user", "content": {}}]],
)
def test_untrusted_message_roles_and_shapes_are_rejected(config, identity, history):
    with pytest.raises(Problem) as error:
        agent.run_turn(identity, history, FakeService(identity))
    assert error.value.code == "INVALID_CONVERSATION"


def test_old_constraints_are_not_silently_truncated(config, identity):
    with pytest.raises(Problem) as error:
        agent.run_turn(identity, HISTORY * 81, FakeService(identity))
    assert error.value.code == "LLM_CONTEXT_LIMIT"


def test_incomplete_unverified_or_silently_reduced_recipe_cannot_prepare(identity):
    service = FakeService(identity)
    session = ToolSession(identity, service)
    with pytest.raises(Problem) as error:
        invoke(session, "publish_meal_plan", meal())
    assert error.value.code == "PRODUCT_NOT_VERIFIED"
    invoke(session, "publish_meal_plan", meal(False))
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", purchase())
    assert error.value.code == "INCOMPLETE_MEAL_PLAN"
    smaller = meal(False)
    smaller["ingredients"].pop()
    with pytest.raises(Problem) as error:
        invoke(session, "publish_meal_plan", smaller)
    assert error.value.code == "INCOMPLETE_MEAL_PLAN"
    assert not any(c[0] == "prepare" for c in service.calls)


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "1e999999999999", "0.000001"])
def test_invalid_ingredient_quantities_are_actionable(identity, amount):
    draft = meal(False)
    draft["ingredients"][0]["amount"] = amount
    with pytest.raises(Problem) as error:
        invoke(ToolSession(identity, FakeService(identity)), "publish_meal_plan", draft)
    assert error.value.code == "INVALID_MEAL_QUANTITY"


def test_basket_exactness_duplicate_ingredient_aggregation_and_stable_retries(identity):
    service = FakeService(identity)
    session = matched_session(identity, service)
    request = purchase()
    request["lines"].pop()
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", request)
    assert error.value.code == "MEAL_BASKET_MISMATCH"
    expanded = meal()
    expanded["ingredients"].append(
        {"name": "extra pasta", "product_id": "pasta", "amount": "0.5", "unit": "KG"}
    )
    invoke(session, "publish_meal_plan", expanded)
    request = purchase()
    request["lines"][0]["amount"] = "20.5"
    invoke(session, "prepare_order", request)
    invoke(session, "prepare_order", request)
    keys = [c[2].idempotency_key for c in service.calls if c[0] == "prepare"]
    assert len(keys) == 2 and keys[0] == keys[1]
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", request | {"budget_gross": "2000"})
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(Problem) as error:
        invoke(session, "publish_meal_plan", meal())
    assert error.value.code == "MEAL_PLAN_LOCKED"


def test_new_customer_turn_can_revise_terms_and_saved_reads_keep_prepared_plan(identity):
    service = FakeService(identity)
    session = matched_session(identity, service)
    invoke(session, "prepare_order", purchase())
    other = proposal(identity)
    service.proposals[other["proposal_id"]] = other
    assert invoke(
        session, "get_proposal", {"proposal_id": other["proposal_id"]}
    ) == session.checked(ProposalResponse, other)
    assert session.result().proposal_id == service.saved["proposal_id"]
    next_session = matched_session(identity | {"_turn_id": str(uuid4())}, service)
    invoke(next_session, "prepare_order", purchase() | {"budget_gross": "2000"})
    keys = [c[2].idempotency_key for c in service.calls if c[0] == "prepare"]
    assert keys[0] != keys[1]


@pytest.mark.parametrize("outcome", ["denied", "needs_resolution"])
def test_blocked_facts_remain_blocked_in_the_final_response(monkeypatch, config, identity, outcome):
    service = FakeService(identity)
    service.saved["policy_outcome"] = outcome
    scripted(monkeypatch, prepared_script() + [reply(text="Review the facts.")])
    result = agent.run_turn(identity, HISTORY, service)
    expected = "cannot be confirmed yet" if outcome == "denied" else "needs checking"
    assert expected in result.text
    assert "Your order" in result.text
    assert "Outside standing scope" not in result.text
    assert "Confirm purchase button" not in result.text


def test_blocked_reply_keeps_the_basket_without_dumping_per_product_errors(identity):
    service = FakeService(identity)
    service.saved["policy_outcome"] = "needs_resolution"
    reasons = [
        {
            "code": "MISSING_PRICE",
            "message": "A complete, consistent sales-unit price and tax basis is required.",
            "product_id": pid,
            "severity": "unresolved",
        }
        for pid in NAMES
    ]
    service.saved["reasons"] = reasons
    session = matched_session(identity, service)
    invoke(session, "prepare_order", purchase())
    result = session.result("Here is your recipe estimate for 200 portions.")
    assert result.proposal_id == service.saved["proposal_id"]
    assert "needs checking before confirmation" in result.text
    assert "tax basis" not in result.text and "MISSING_PRICE" not in result.text
    assert service.saved["reasons"] == reasons  # detailed purchasing checks are retained
    assert len(result.text) < 300


@pytest.mark.parametrize(
    "outcome", ["ready_to_commit", "approval_required", "needs_resolution", "denied"]
)
def test_purchasing_warnings_are_never_appended_as_chat_prose(identity, outcome):
    service = FakeService(identity)
    service.saved["policy_outcome"] = outcome
    warning = {
        "code": "VARIABLE_WEIGHT",
        "message": "Sold by variable weight: the final weight and price settle at delivery, "
        "so this price is an estimate.",
        "severity": "warning",
    }
    service.saved["reasons"] = [warning] * 6
    session = matched_session(identity, service)
    invoke(session, "prepare_order", purchase())
    narrative = "Here is your carbonara recipe estimate for 200 portions."
    result = session.result(narrative)
    assert result.proposal_id == service.saved["proposal_id"]
    assert "variable weight" not in result.text
    assert service.saved["reasons"] == [warning] * 6
    if outcome in ("ready_to_commit", "approval_required"):
        assert result.text == narrative
        assert "ready to review" in session.result().text  # recovery still has a trusted reply
    else:
        assert "Your order" in result.text and len(result.text) < 160


def test_matched_recipe_reply_does_not_gain_a_disclaimer_or_checkout_script(identity):
    session = matched_session(identity, FakeService(identity))
    narrative = "Here is your carbonara recipe estimate for 200 portions."
    result = session.result(narrative)
    assert result.text == narrative
    assert result.meal_plan == MealPlan(**meal())
    assert result.proposal_id is None
    guidance = session.execution_guidance(30)
    assert "Do not ask for delivery details." in guidance
    assert "ask only for missing delivery details" not in guidance


@pytest.mark.parametrize("automatic", [False, True])
def test_provider_knows_whether_delivery_defaults_are_staged_automatically(
    monkeypatch, config, identity, automatic
):
    config.cart_auto_prepare = automatic
    seen = scripted(monkeypatch, [reply(text="What would you like to cook?")])
    agent.run_turn(identity, HISTORY, FakeService(identity))
    instructions = seen[0]["messages"][0]["content"]
    assert "Do not ask for a delivery date, destination, location or address in chat." in instructions
    assert "normally in one or two short sentences" in instructions
    assert "Use at most three short sentences" not in instructions
    assert "ask only for missing delivery details" not in instructions
    assert ("Automatic cart preparation is enabled" in instructions) == automatic
    if automatic:
        assert "tomorrow in Helsinki" in instructions
        assert "Do not say you are waiting for delivery details" in instructions


@pytest.mark.parametrize(
    "final",
    [
        reply(),
        reply(text="   "),
        Problem("LLM_UNAVAILABLE", "provider failed", 503),
        Problem("LLM_TIMEOUT", "deadline reached", 504),
    ],
)
def test_provider_failure_after_preparation_keeps_the_verified_result(
    monkeypatch, config, identity, final
):
    service = FakeService(identity)
    # An empty final reply is retried once (stop control), so the same failure is scripted twice.
    scripted(monkeypatch, prepared_script() + [final, final])
    events = []
    result = agent.run_turn(identity, HISTORY, service, on_progress=events.append)
    assert result.proposal_id == service.saved["proposal_id"]
    assert result.meal_plan == MealPlan(**meal())
    assert events[-1].kind == "complete"
    assert events[-1].error_code in ("LLM_RESPONSE_INVALID", "LLM_UNAVAILABLE", "LLM_TIMEOUT")


def test_empty_reply_without_preparation_is_a_failure(monkeypatch, config, identity):
    # The model call is retried once (stop control); a second empty reply still fails the turn.
    scripted(monkeypatch, [reply(), reply()])
    with pytest.raises(Problem) as error:
        agent.run_turn(identity, HISTORY, FakeService(identity))
    assert error.value.code == "LLM_RESPONSE_INVALID"


def test_error_limit_stops_inside_a_batch_before_later_tool_calls(monkeypatch, config, identity):
    seen = scripted(
        monkeypatch, [reply(*[call("commit_order") for _ in range(4)], call("get_purchase_policy"))]
    )
    service = FakeService(identity)
    events = []
    result = agent.run_turn(identity, HISTORY, service, on_progress=events.append)
    assert "tool errors" in result.text and len(seen) == 1
    assert service.calls == []
    assert events[-1].error_code == "TOOL_ERROR_LIMIT"
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert all(e.tool is None for e in events)


@pytest.mark.parametrize("rejections", [1, 2])
def test_request_brief_gets_one_correction_before_asking_customer(
    monkeypatch, config, identity, rejections
):
    attempts = []

    def check(self, previous, proposed, structured_changes=()):
        attempts.append(proposed)
        if len(attempts) <= rejections:
            raise Problem("REQUEST_BRIEF_UNVERIFIED", "Clarify the request.", 422)

    monkeypatch.setattr(Guardrails, "check_request_brief", check)
    brief = {"intent": "build_list", "goal": "Lasagna", "starting_point": "dish", "portions": 50}
    seen = scripted(monkeypatch, [
        reply(call("record_request", brief)),
        reply(call("record_request", brief), call("get_product", {"product_id": "milk"})),
        reply(text="Let's work out the ingredients."),
    ])
    service = FakeService(identity)
    events = []
    result = agent.run_turn(identity, HISTORY, service, on_progress=events.append)
    assert len(attempts) == 2
    assert result.proposal_id is None and result.meal_plan is None
    assert events[-1].kind == "complete"
    if rejections == 2:
        assert len(seen) == 2  # No third provider call that can hang or time out.
        assert service.calls == []  # Stop the batch before subsequent tools.
        assert "one message" in result.text
        assert events[-1].error_code == "REQUEST_BRIEF_UNVERIFIED"
    else:
        assert len(seen) == 3
        assert [c[0] for c in service.calls] == ["product"]
        assert result.text == "Let's work out the ingredients."
        assert events[-1].error_code is None


def test_progress_shows_thinking_each_round_and_reviewing_only_when_guarded(
    monkeypatch, config, identity
):
    def kinds(events):
        return [(e.kind, e.tool) for e in events]

    scripted(monkeypatch, [reply(call("get_product", {"product_id": "1"})), reply(text="Hi")])
    events = []
    agent.run_turn(identity, HISTORY, FakeService(identity), on_progress=events.append)
    # Guardrails are off in tests, so no reply review is shown.
    assert kinds(events) == [
        ("started", None),
        ("thinking", None),
        ("tool_started", "get_product"),
        ("tool_completed", "get_product"),
        ("thinking", None),
        ("complete", None),
    ]

    class Reviewed(Guardrails):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.mode = "shadow"

        def screen_input(self):
            return None

        def review_output(self, session, narrative, tool_log):
            return narrative

    monkeypatch.setattr(agent, "Guardrails", Reviewed)
    scripted(monkeypatch, [reply(text="Hi")])
    events = []
    agent.run_turn(identity, HISTORY, FakeService(identity), on_progress=events.append)
    assert [e.kind for e in events] == ["started", "thinking", "reviewing", "complete"]
    assert [e.sequence for e in events] == [1, 2, 3, 4]


def test_failed_tools_are_logged_without_progress_observer(monkeypatch, config, identity, caplog):
    scripted(
        monkeypatch,
        [
            reply(
                *[
                    call("get_product", {"private-unknown-field": "private-tool-value"})
                    for _ in range(4)
                ]
            )
        ],
    )
    with caplog.at_level(logging.INFO):
        result = agent.run_turn(identity, HISTORY, FakeService(identity))
    assert "tool errors" in result.text
    rows = [json.loads(r.message) for r in caplog.records if r.name == "aimo.operations"]
    failed = [r for r in rows if r["event"] == "agent.tool_failed"]
    assert len(failed) == 4
    assert all(
        r["tool"] == "get_product"
        and r["error_code"] == "INVALID_TOOL_ARGUMENTS"
        and r["turn_id"] == identity["_turn_id"]
        and r["duration_ms"] >= 0
        for r in failed
    )
    assert any(r.get("error_code") == "TOOL_ERROR_LIMIT" for r in rows)
    invalid = next(r for r in rows if r["event"] == "tool.arguments_invalid")
    assert "product_id" in invalid["invalid_fields"]
    assert "<unknown>" in invalid["invalid_fields"]
    assert all(
        s not in caplog.text
        for s in (
            "private-tool-value",
            "private-unknown-field",
            "private-provider-key",
            HISTORY[0]["content"],
        )
    )


def test_reasoning_signatures_survive_tool_round_without_logging(config, caplog):
    config.llm_model = "anthropic/claude-sonnet-5.5"
    config.llm_reasoning_effort = "low"
    config.llm_max_completion_tokens = 8192
    reasoning = [
        {
            "type": "reasoning.encrypted",
            "data": "private-reasoning-signature",
            "id": "thinking-block",
            "format": "anthropic-claude-v1",
            "index": 0,
        }
    ]
    tool = call("get_purchase_policy")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        message = (
            reply(tool) | {"reasoning_details": reasoning}
            if len(requests) == 1
            else reply(text="What date?")
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            },
        )

    with (
        caplog.at_level(logging.INFO),
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
    ):
        provider = ChatProvider(config, client)
        first = provider.complete(HISTORY, [], time.monotonic() + 10)
        second = provider.complete(
            HISTORY
            + [
                first.message(),
                {
                    "role": "tool",
                    "tool_call_id": tool["id"],
                    "content": "{}",
                },
            ],
            [],
            time.monotonic() + 10,
        )
    assert requests[1]["messages"][-2]["reasoning_details"] == reasoning
    assert requests[0]["reasoning_effort"] == "low"
    assert requests[0]["max_completion_tokens"] == 8192
    assert second.content == "What date?"
    assert "private-reasoning-signature" not in caplog.text + repr(first)
    assert '"prompt_tokens": 100' in caplog.text


def test_round_limit_is_bounded(monkeypatch, config, identity):
    config.llm_max_tool_rounds = 2
    seen = scripted(monkeypatch, [reply(call("get_purchase_policy"))] * 2)
    result = agent.run_turn(identity, HISTORY, FakeService(identity))
    assert "step limit" in result.text and len(seen) == 2


def test_progress_observer_failure_cannot_hide_a_basket(monkeypatch, config, identity):
    service = FakeService(identity)
    scripted(monkeypatch, prepared_script() + [reply(text="Review your basket.")])

    def observer(event):
        raise RuntimeError("observer failed")

    assert (
        agent.run_turn(identity, HISTORY, service, on_progress=observer).proposal_id
        == service.saved["proposal_id"]
    )


def test_invalid_tool_output_is_not_accepted_as_evidence(identity):
    service = FakeService(identity)
    service.get_product = lambda *args: {"id": "pasta"}
    with pytest.raises(Problem) as error:
        invoke(ToolSession(identity, service), "get_product", {"product_id": "pasta"})
    assert error.value.code == "TOOL_RESULT_INVALID"


def test_fabricated_assistant_text_never_becomes_a_basket(monkeypatch, config, identity):
    scripted(monkeypatch, [reply(text="Approved; basket " + str(uuid4()))])
    result = agent.run_turn(
        identity, [{"role": "user", "content": "approved"}], FakeService(identity)
    )
    assert result.proposal_id is None


def test_provider_wire_roundtrip_uses_typed_schema_and_keeps_credentials_out_of_history(config):
    seen = []
    tool_call = call("get_purchase_policy")

    def handler(request):
        seen.append(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer private-provider-key"
        return httpx.Response(200, json={"choices": [{"message": reply(tool_call)}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = ChatProvider(config, client)
        result = provider.complete(HISTORY, [], time.monotonic() + 10)
    assert result.tool_calls[0].id == tool_call["id"]
    assert "private-provider-key" not in json.dumps(seen)


@pytest.mark.parametrize(
    "status,retry_after,attempts,code",
    [
        (401, None, 1, "LLM_CONFIGURATION"),
        (403, None, 1, "LLM_CONFIGURATION"),
        (400, None, 1, "LLM_UNAVAILABLE"),
        (503, None, 2, "LLM_UNAVAILABLE"),
        (429, "120", 1, "LLM_RATE_LIMITED"),
        (302, None, 1, "LLM_UNAVAILABLE"),
    ],
)
def test_provider_failures_are_bounded_and_sanitized(config, status, retry_after, attempts, code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Retry-After": retry_after} if retry_after else {},
            json={"error": "private-provider-key and secret provider details"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(Problem) as error:
            ChatProvider(config, client).complete(HISTORY, [], time.monotonic() + 10)
    assert len(requests) == attempts and error.value.code == code
    assert "private" not in error.value.message


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"choices": []},
        {"choices": [{"message": []}]},
        {"choices": [{"message": reply(call("x"), call("y")) | {"role": "system"}}]},
        {"choices": [{"message": reply(), "finish_reason": "length"}]},
    ],
)
def test_malformed_provider_responses_are_actionable(config, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(Problem) as error:
            ChatProvider(config, client).complete(HISTORY, [], time.monotonic() + 10)
    assert error.value.code == "LLM_RESPONSE_INVALID"


def test_duplicate_provider_call_ids_are_invalid(config):
    repeated = call("get_purchase_policy")
    with pytest.raises(Problem) as error:
        ChatProvider.parse(
            json.dumps({"choices": [{"message": reply(repeated, repeated)}]}).encode()
        )
    assert error.value.code == "LLM_RESPONSE_INVALID"


def test_missing_configuration_and_deadline_do_not_call_provider(config):
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: pytest.fail("unexpected request"))
    ) as client:
        config.llm_api_key = ""
        with pytest.raises(Problem) as error:
            ChatProvider(config, client)
        assert error.value.code == "LLM_NOT_CONFIGURED"
        config.llm_api_key = "private-provider-key"
        with pytest.raises(Problem) as error:
            ChatProvider(config, client).complete(HISTORY, [], time.monotonic() - 1)
        assert error.value.code == "LLM_TIMEOUT"


def test_network_retry_can_recover_within_the_same_deadline(config):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("secret network detail", request=request)
        return httpx.Response(200, json={"choices": [{"message": reply(text="Which date?")}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ChatProvider(config, client).complete(HISTORY, [], time.monotonic() + 10)
    assert result.content == "Which date?" and len(requests) == 2


def test_persistent_network_failure_stops_after_one_retry(config):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("secret network detail", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(Problem) as error:
            ChatProvider(config, client).complete(HISTORY, [], time.monotonic() + 10)
    assert error.value.code == "LLM_UNAVAILABLE" and len(requests) == 2
    assert "secret" not in error.value.message


@pytest.mark.parametrize(
    "url",
    [
        "invalid",
        "http://provider.test/v1",
        "http://localhost.evil.test/v1",
        "http://192.168.1.10/v1",
        "https://user:secret@provider.test/v1",
        "https://provider.test:invalid",
        "https://[invalid",
    ],
)
def test_invalid_provider_configuration_is_actionable(config, url):
    config.llm_base_url = url
    with httpx.Client() as client:
        with pytest.raises(Problem) as error:
            ChatProvider(config, client)
    assert error.value.code == "LLM_CONFIGURATION"
    assert "secret" not in error.value.message


def test_provider_context_and_response_limits(config):
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: pytest.fail("oversize context sent"))
    ) as client:
        with pytest.raises(Problem) as error:
            ChatProvider(config, client).complete(
                [{"role": "user", "content": "x" * 512_000}], [], time.monotonic() + 10
            )
    assert error.value.code == "LLM_CONTEXT_LIMIT"
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"x" * 1_000_001))
    ) as client:
        with pytest.raises(Problem) as error:
            ChatProvider(config, client).complete(HISTORY, [], time.monotonic() + 10)
    assert error.value.code == "LLM_RESPONSE_INVALID"


def test_provider_tool_call_count_and_argument_size_are_bounded():
    for response in (reply(*[call("x") for _ in range(13)]), reply(call("x", {"x": "a" * 64_000}))):
        with pytest.raises(Problem) as error:
            ChatProvider.parse(json.dumps({"choices": [{"message": response}]}).encode())
        assert error.value.code == "LLM_RESPONSE_INVALID"


def test_backend_result_scope_is_checked_before_associating_a_purchase(identity):
    service = FakeService(identity)
    service.saved["buyer_id"] = "different-buyer"
    session = matched_session(identity, service)
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", purchase())
    assert error.value.code == "TOOL_RESULT_INVALID" and session.result().proposal_id is None


def test_long_narrative_keeps_authoritative_state_notice(identity):
    service = FakeService(identity)
    service.saved["policy_outcome"] = "denied"
    session = matched_session(identity, service)
    invoke(session, "prepare_order", purchase())
    result = session.result("x" * 20_000)
    assert len(result.text) <= 20_000
    assert result.text.endswith(
        "This basket cannot be confirmed yet; see purchasing checks in Your order."
    )


def test_variable_weight_estimate_stays_available_on_the_basket(identity):
    """The card retains estimate evidence without injecting technical warnings into chat."""
    service = FakeService(identity)
    service.saved["policy_outcome"] = "ready_to_commit"
    service.saved["reasons"] = [
        {
            "code": "VARIABLE_WEIGHT_UNRESOLVED",
            "message": "Sold by variable weight: the final price is an estimate.",
            "product_id": "p",
            "severity": "warning",
        }
    ]
    session = matched_session(identity, service)
    invoke(session, "prepare_order", purchase())
    text = session.result("Here is your basket.").text
    assert text == "Here is your basket."
    assert session.proposal["reasons"] == service.saved["reasons"]


def test_unsupported_dietary_tool_fields_require_resolution(identity):
    request = purchase() | {"requirements": {"vegan": True}}
    service = FakeService(identity)
    session = matched_session(identity, service)
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", request)
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"
    assert not any(c[0] == "prepare" for c in service.calls)


@pytest.mark.parametrize(
    "url", ["http://localhost:8000/v1", "http://127.0.0.1/v1", "http://[::1]/v1"]
)
def test_loopback_provider_is_allowed_for_local_development(config, url):
    config.llm_base_url = url
    with httpx.Client() as client:
        assert ChatProvider(config, client).url == url + "/chat/completions"


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize(
    "failure", [RuntimeError("private-provider-key"), httpx.ConnectError("private-provider-key")]
)
def test_unexpected_tool_failure_is_safe_and_preserves_saved_basket(
    monkeypatch, config, identity, prepared, failure, caplog
):
    service = FakeService(identity)
    attempts = []

    def fail(*args):
        attempts.append(1)
        raise failure

    # get_proposal still runs after the basket (the policy lookup is refused there by stop control
    # unless the customer asks for it), so the failure is a real tool failure after the basket.
    service.get_proposal = fail
    scripted(
        monkeypatch,
        (prepared_script() if prepared else [])
        + [reply(call("get_proposal", {"proposal_id": service.saved["proposal_id"]}))],
    )
    events = []
    if prepared:
        result = agent.run_turn(identity, HISTORY, service, on_progress=events.append)
        assert result.proposal_id == service.saved["proposal_id"]
        assert result.meal_plan == MealPlan(**meal())
        assert events[-1].kind == "complete"
    else:
        with pytest.raises(Problem) as error:
            agent.run_turn(identity, HISTORY, service, on_progress=events.append)
        assert error.value.code == "TOOL_EXECUTION_FAILED"
        assert "private-provider-key" not in error.value.message
    assert attempts == [1]
    assert any(e.kind == "tool_failed" and e.error_code == "TOOL_EXECUTION_FAILED" for e in events)
    assert any(e.kind == "error" and e.error_code == "TOOL_EXECUTION_FAILED" for e in events)
    assert "private-provider-key" not in caplog.text + str(events)


@pytest.mark.parametrize("prepared", [False, True])
def test_unexpected_provider_failure_is_safe_and_preserves_saved_basket(
    monkeypatch, config, identity, prepared, caplog
):
    service = FakeService(identity)
    scripted(
        monkeypatch,
        (prepared_script() if prepared else []) + [RuntimeError("private-provider-key")],
    )
    events = []
    if prepared:
        result = agent.run_turn(identity, HISTORY, service, on_progress=events.append)
        assert result.proposal_id == service.saved["proposal_id"]
        assert events[-1].kind == "complete"
    else:
        with pytest.raises(Problem) as error:
            agent.run_turn(identity, HISTORY, service, on_progress=events.append)
        assert error.value.code == "AGENT_FAILED"
        assert "private-provider-key" not in error.value.message
    assert any(e.kind == "error" and e.error_code == "AGENT_FAILED" for e in events)
    assert "private-provider-key" not in caplog.text + str(events)


def test_unmatched_recipe_keeps_a_brief_notice_and_ingredient_details_in_the_plan(identity):
    session = ToolSession(identity, FakeService(identity))
    invoke(session, "publish_meal_plan", meal(matched=False))
    result = session.result("All ready.")
    assert result.text == "All ready.\n\n5 ingredients still need product matches."
    assert result.meal_plan == MealPlan(**meal(matched=False))
    assert result.proposal_id is None


def test_direct_product_request_works_alongside_recipe_tools(monkeypatch, config, identity):
    service = FakeService(identity)
    plan = {
        "title": "10 kg butter",
        "portions": 1,
        "ingredients": [{"name": "Butter", "amount": "10", "unit": "KG", "product_id": "butter"}],
    }
    request = purchase() | {"lines": [{"product_id": "butter", "unit": "KG", "amount": "10"}]}
    seen = scripted(
        monkeypatch,
        [
            reply(call("get_product", {"product_id": "butter"})),
            reply(call("publish_meal_plan", plan)),
            reply(call("prepare_order", request)),
            reply(text="Your requested butter basket is ready to review."),
        ],
    )
    turn = agent.run_turn(identity, [{"role": "user", "content": "Order 10 kg butter"}], service)
    assert turn.proposal_id == service.saved["proposal_id"]
    prompt = seen[0]["messages"][0]["content"]
    assert "direct product requests" in prompt and "10 kg butter" in prompt
    assert "search_recipes" in prompt
    assert "For the first scenario" not in prompt
    assert [c[0] for c in service.calls].count("prepare") == 1


def test_prompt_sections_can_be_reworded_without_breaking_recipe_turns(
    monkeypatch, config, identity
):
    monkeypatch.setattr(agent, "ORDINARY_PURCHASE_PROMPT", "Reworded ordinary purchase guidance.")
    monkeypatch.setattr(agent, "SAFETY_PROMPT", "Reworded safety guidance.")
    seen = scripted(monkeypatch, [reply(text="How many portions do you need?")])
    assert agent.run_turn(identity, HISTORY, FakeService(identity)).text
    prompt = seen[0]["messages"][0]["content"]
    assert "Reworded safety guidance." in prompt and "search_recipes" in prompt


def test_q44_basket_mismatch_says_exactly_what_to_send(identity):
    """The plan needs 20 KG pasta + 0.5 KG pasta; one 20 KG line is refused with 'pasta 20.5 KG'."""
    service = FakeService(identity)
    session = matched_session(identity, service)
    expanded = meal()
    expanded["ingredients"].append(
        {"name": "extra pasta", "product_id": "pasta", "amount": "0.5", "unit": "KG"}
    )
    invoke(session, "publish_meal_plan", expanded)
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", purchase())  # pasta is 20 KG, the plan needs 20.5 KG
    assert error.value.code == "MEAL_BASKET_MISMATCH" and error.value.status == 422
    assert "pasta 20.5 KG" in error.value.message
    details = error.value.details
    assert details["wrong_amount_or_unit"] == [
        {
            "product_id": "pasta",
            "required": {"amount": "20.5", "unit": "KG"},
            "sent": {"amount": "20", "unit": "KG"},
        }
    ]
    assert details["missing"] == [] and details["unexpected"] == []
    pasta = next(r for r in details["required"] if r["product_id"] == "pasta")
    assert (pasta["amount"], pasta["unit"]) == ("20.5", "KG")
    assert pasta["ingredients"] == ["extra pasta", "pasta"]
    assert not any(c[0] == "prepare" for c in service.calls)


def test_q44_model_sees_the_details_in_the_tool_error(monkeypatch, config, identity):
    expanded = meal()
    expanded["ingredients"].append(
        {"name": "extra pasta", "product_id": "pasta", "amount": "0.5", "unit": "KG"}
    )
    seen = scripted(
        monkeypatch,
        [
            reply(*[call("get_product", {"product_id": name}) for name in NAMES]),
            reply(call("publish_meal_plan", expanded)),
            reply(call("prepare_order", purchase())),
            reply(text="Retrying with pasta 20.5 KG."),
            # no plan-only mode: the model stopped without a basket, so the server continues once
            reply(text="I will retry with the corrected amounts."),
        ],
    )
    agent.run_turn(identity, HISTORY, FakeService(identity))
    tool = [m for m in seen[-1]["messages"] if m["role"] == "tool"][-1]
    error = json.loads(tool["content"])["error"]
    assert error["code"] == "MEAL_BASKET_MISMATCH"
    assert error["details"]["wrong_amount_or_unit"][0]["required"] == {
        "amount": "20.5",
        "unit": "KG",
    }


def test_selected_recipe_streams_unmatched_matched_and_checked_prices(monkeypatch, config, identity):
    service = FakeService(identity)
    saved = meal(False) | {"recipe_plan_id": str(uuid4()), "recipe_plan_revision": 1}
    for item in saved["ingredients"]:
        item.update(ingredient_id=item["name"], status="unresolved")
    service.get_recipe = lambda *_: {
        "recipe": {
            "id": "recipe", "title": "Carbonara", "summary": "Authored recipe",
            "base_servings": 4, "category": "main", "instructions": [],
            "ingredients": [{"id": "pasta", "name": "Pasta", "quantity": "400",
                             "unit": "g", "scaling": "linear", "form": "dry"}],
        },
        "version": "v1", "source": "fixture", "attribution": "Authored", "license": "test",
    }
    service.scale_recipe = lambda actor, request: deepcopy(saved)

    def match(actor, request):
        item = saved["ingredients"][0]
        item.update(product_id="pasta", status="matched", purchase_amount="20", purchase_unit="KG")
        saved["recipe_plan_revision"] += 1
        return deepcopy(saved)

    service.match_ingredient = match
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    evidence = {
        "product_id": "pasta", "currency": "EUR", "net": "10", "gross": "11.4",
        "tax_rate": "0.14", "available_sales_quantity": "100", "expires_at": expiry,
        "reasons": [], "mode": "fixture", "observed_at": datetime.now(timezone.utc),
        "source": {"price": {"private_raw": "omit"}, "availability": None},
        "sales_unit": "BOX", "base_unit": "KG", "price_basis": "per_sales_unit",
    }
    service.check_price_and_availability = lambda actor, request: {
        "mode": "fixture", "products": {"pasta": evidence}
    }
    scripted(monkeypatch, [
        reply(call("scale_recipe", {"recipe_id": "recipe", "version": "v1", "portions": 200})),
        reply(call("get_product", {"product_id": "pasta"})),
        reply(call("match_ingredient", {"plan_id": saved["recipe_plan_id"], "revision": 1,
                                       "ingredient_id": "pasta", "product_id": "pasta"})),
        reply(call("check_price_and_availability", {"product_ids": ["pasta"],
                                                   "delivery_date": "2026-11-17"})),
        reply(text="Four ingredients still need matches."),
    ])
    events = []
    result = agent.run_turn(identity, HISTORY, service, on_progress=events.append)
    drafts = [e.draft for e in events if e.kind == "tool_completed"]
    assert len(drafts[0].items) == 5 and not any(i.matched for i in drafts[0].items)
    assert not any(i.matched for i in drafts[1].items)  # Reading a candidate does not select it.
    assert drafts[2].items[0].matched and drafts[2].items[0].price is None
    price = drafts[3].items[0].price
    assert price.gross == "11.4" and price.sales_unit == "BOX"  # Not 20 * a box price.
    assert price.mode == "fixture" and price.delivery_date == "2026-11-17"
    assert "private_raw" not in drafts[3].model_dump_json()
    assert drafts[3].proposal_id is None and result.proposal_id is None
    assert events[-1].draft == drafts[-1]
    from aimo.chat_draft import cart_snapshot

    session = matched_session(identity, service)
    session.commercial = {"pasta": evidence | {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}}
    session.commercial_dates = {"pasta": "2026-11-17"}
    assert cart_snapshot(session, plan_visible=True).items[0].price is None
    assert cart_snapshot(session, plan_visible=False) is None
    session.commercial["pasta"] = evidence | {"reasons": [{
        "code": "PRICE_OUTSIDE_VALIDITY", "severity": "unresolved",
        "message": "Not valid for requested delivery", "product_id": "pasta",
    }]}
    assert cart_snapshot(session, plan_visible=True).items[0].price is None


@pytest.mark.parametrize("count", [12, 13, 22, 100])
def test_openai_compatible_large_read_batch_keeps_every_call(count):
    response = reply(*[call("search_products", {"query": f"ingredient-{i}"}) for i in range(count)])
    parsed = ChatProvider.parse(json.dumps({"choices": [{"message": response}]}).encode())
    assert parsed.message()["tool_calls"] == response["tool_calls"]
