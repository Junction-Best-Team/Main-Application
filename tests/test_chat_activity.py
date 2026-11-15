"""Authored worker activity: persistence, attempt fencing and authenticated SSE."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from wsc_support import add_second_buyer

from aimo import agent, conversations
from aimo.agent import AgentProgress, Progress
from aimo.agent_tools import ToolSession
from aimo.api import create_app
from aimo.chat_activity import TOOL_LABELS, record_progress, tool_detail
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest
from aimo.db import Problem, close_pools, connection, now
from aimo.worker import run_once


def queue(buyer):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    body = MessageRequest(text="Plan lunch", idempotency_key=str(uuid4()))
    assert conversations.enqueue(buyer, cid, body)["activity"]["state"] == "queued"
    return cid, body


def test_real_worker_wires_observer_and_keeps_every_fast_tool_event(buyer, service, monkeypatch):
    cid, body = queue(buyer)

    def runner(actor, history, shared, *, on_progress, ensure_live=None):
        progress = Progress(actor["_turn_id"], on_progress)
        progress.emit("started")
        progress.emit("thinking")
        for tool in ("search_recipes", "get_recipe", "search_products", "get_product"):
            progress.emit("tool_started", tool)
            live = conversations.detail(buyer, cid)
            assert live["busy"] and live["activity"]["events"][-1]["kind"] == "tool_started"
            progress.emit("tool_completed", tool)
        # Unknown/model-supplied names and error details must never reach the browser.
        progress.emit("tool_started", "private-unknown-tool-name")
        progress.emit("tool_failed", "private-unknown-tool-name", "PRIVATE_ERROR_DETAIL")
        progress.emit("thinking")
        progress.emit("reviewing")
        progress.emit("complete")
        return AgentTurn(text="What date?")

    monkeypatch.setattr(agent, "run_turn", runner)
    assert run_once(service)
    result = conversations.detail(buyer, cid)
    events = result["activity"]["events"]
    assert result["activity"]["state"] == "complete" and not result["busy"]
    assert [e["sequence"] for e in events] == list(range(1, 16))
    assert [e["label"] for e in events[:3]] == [
        "Checking your request", "Thinking", "Searching recipes"
    ]
    assert events[6]["label"] == "Searching products"
    assert events[-4] == {"sequence": 12, "kind": "tool_failed", "label": "Using a tool"}
    assert [e["label"] for e in events[-3:-1]] == ["Thinking", "Reviewing the reply"]
    assert "PRIVATE" not in json.dumps(events) and "private-unknown" not in json.dumps(events)
    close_pools()
    assert conversations.detail(buyer, cid) == result
    assert conversations.enqueue(buyer, cid, body) == result  # Retry adds no duplicate activity.
    assert not run_once(service)
    next_body = MessageRequest(text="Next lunch", idempotency_key=str(uuid4()))
    # A new turn in this conversation starts empty and does not borrow the old activity.
    next_turn = conversations.enqueue(buyer, cid, next_body)
    assert next_turn["activity"]["events"] == []


@pytest.mark.parametrize("code", ["TOOL_ERROR_LIMIT", "TOOL_ROUND_LIMIT", "REQUEST_BRIEF_UNVERIFIED"])
def test_terminal_error_code_remains_an_interruption_after_sanitization(
    buyer, service, monkeypatch, caplog, code
):
    cid, _ = queue(buyer)

    def runner(actor, history, shared, *, on_progress, **kwargs):
        progress = Progress(actor["_turn_id"], on_progress)
        progress.emit("complete", error_code=code)
        return AgentTurn(text="Progress is saved; please continue.")

    monkeypatch.setattr(agent, "run_turn", runner)
    with caplog.at_level("INFO", logger="aimo.operations"):
        assert run_once(service)
    activity = conversations.detail(buyer, cid)["activity"]
    assert activity["state"] == "complete"
    assert activity["events"] == [
        {"sequence": 1, "kind": "error", "label": "Response interrupted"}
    ]
    assert code not in json.dumps(activity)
    rows = [json.loads(r.message) for r in caplog.records if r.name == "aimo.operations"]
    assert next(r for r in rows if r["event"] == "chat.persisted")["partial"] is True


def test_expired_replaced_and_out_of_order_progress_cannot_publish(buyer, service):
    cid, _ = queue(buyer)
    old = conversations.claim_turn(cid)
    first = AgentProgress(str(old["id"]), 1, "tool_started", "get_recipe")
    record_progress(old, first)
    record_progress(old, first)
    record_progress(old, AgentProgress(str(uuid4()), 2, "tool_completed", "get_recipe"))
    assert len(conversations.detail(buyer, cid)["activity"]["events"]) == 1
    with connection() as c:
        c.execute("UPDATE conversation_turns SET lease_until=%s WHERE id=%s",
                  (now() - timedelta(seconds=1), old["id"]))
    record_progress(old, AgentProgress(str(old["id"]), 2, "tool_completed", "get_recipe"))
    expired = conversations.detail(buyer, cid)
    assert not expired["busy"] and expired["activity"]["state"] == "failed"
    assert len(expired["activity"]["events"]) == 1
    current = conversations.claim_turn(cid)
    record_progress(current, AgentProgress(str(current["id"]), 1, "tool_started", "get_product"))
    record_progress(old, AgentProgress(str(old["id"]), 3, "tool_failed", "get_recipe"))
    live = conversations.detail(buyer, cid)
    assert live["activity"]["events"] == [
        {"sequence": 1, "kind": "tool_started", "label": "Checking a product"}
    ]
    conversations.execute_turn(current, service, lambda *args: AgentTurn(text="Done"))
    record_progress(current, AgentProgress(str(current["id"]), 2, "tool_completed", "get_product"))
    assert conversations.detail(buyer, cid)["activity"]["events"] == live["activity"]["events"]


def test_failure_and_explicit_retry_reset_activity(buyer, service, monkeypatch):
    cid, body = queue(buyer)

    def fail(actor, history, shared, *, on_progress, ensure_live=None):
        on_progress(AgentProgress(actor["_turn_id"], 1, "tool_started", "get_recipe"))
        raise Problem("TOOL_EXECUTION_FAILED", "private details", 503)

    monkeypatch.setattr(agent, "run_turn", fail)
    with pytest.raises(Problem):
        run_once(service)
    assert conversations.detail(buyer, cid)["activity"]["state"] == "failed"
    retry = conversations.enqueue(buyer, cid, body)
    assert retry["activity"]["state"] == "queued" and retry["activity"]["events"] == []


def test_activity_is_scoped_and_in_the_authenticated_sse_snapshot(buyer, service, monkeypatch):
    from test_conversations import signed

    cid, _ = queue(buyer)
    turn = conversations.claim_turn(cid)
    record_progress(turn, AgentProgress(str(turn["id"]), 1, "tool_started", "search_recipes"))
    other = add_second_buyer()["approver"]
    with pytest.raises(Problem) as error:
        conversations.detail(other, cid)
    assert error.value.status == 404
    checks = 0

    async def disconnected(request):
        nonlocal checks
        checks += 1
        return checks > 1  # One real snapshot then close, rather than waiting 25 seconds.

    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    with TestClient(create_app(service)) as client:
        assert client.get(f"/api/conversations/{cid}/events").status_code == 401
        signed(client)
        response = client.get(f"/api/conversations/{cid}/events")
    assert response.status_code == 200
    # Streams end by design, so the browser is told to reconnect after one second.
    assert response.text.startswith("retry: 1000\n\n")
    data = json.loads(response.text.split("data: ")[1].split("\n")[0])
    assert data["busy"] and data["activity"]["events"][0]["label"] == "Searching recipes"
    assert response.headers["x-accel-buffering"] == "no"


def test_all_registered_tools_have_product_activity_labels(service):
    session = ToolSession({"_turn_id": str(uuid4())}, service)
    assert set(session.registry) == set(TOOL_LABELS)


def test_draft_cart_persists_streams_and_is_fenced_without_purchasing_authority(buyer, service, monkeypatch):
    from test_conversations import signed

    from aimo.chat_schemas import DraftCart, DraftCartItem, DraftPrice

    cid, _ = queue(buyer)
    turn = conversations.claim_turn(cid)
    draft = DraftCart(turn_id=str(turn["id"]), title="Lunch", items=[
        DraftCartItem(name="Milk", amount="10", unit="L"),
        DraftCartItem(name="Salt", amount=None, unit="g"),
    ])
    record_progress(turn, AgentProgress(str(turn["id"]), 1, "tool_completed", "scale_recipe",
                                       draft=draft, draft_updated=True))
    first = conversations.detail(buyer, cid)
    assert len(first["draft_cart"]["items"]) == 2 and first["purchases"] == []
    draft.items[0].matched = True
    draft.items[0].product_id = "464306"
    draft.items[0].price = DraftPrice(
        gross="1.14", currency="EUR", sales_unit="L", mode="fixture", delivery_date="2026-11-17",
        observed_at=now(), expires_at=now() + timedelta(minutes=10),
    )
    record_progress(turn, AgentProgress(str(turn["id"]), 2, "tool_completed", "check_price_and_availability",
                                       draft=draft, draft_updated=True))
    close_pools()
    loaded = conversations.detail(buyer, cid)
    assert loaded["draft_cart"]["items"][0]["price"]["gross"] == "1.14"
    # No quote or draft has created a proposal/order, and another buyer cannot read it.
    assert loaded["purchases"] == []
    other = add_second_buyer()["approver"]
    with pytest.raises(Problem):
        conversations.detail(other, cid)
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
    count = 0

    async def disconnected(request):
        nonlocal count
        count += 1
        return count > 1

    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    with TestClient(create_app(service)) as client:
        signed(client)
        response = client.get(f"/api/conversations/{cid}/events")
    data = json.loads(response.text.split("data: ")[1].split("\n")[0])
    assert data["draft_cart"] == loaded["draft_cart"]
    # An older sequence cannot overwrite a newer match; expired evidence is hidden on read.
    record_progress(turn, AgentProgress(str(turn["id"]), 1, "tool_completed", "scale_recipe",
                                       draft=None, draft_updated=True))
    assert conversations.detail(buyer, cid)["draft_cart"] == loaded["draft_cart"]
    draft.items[0].price.expires_at = now() - timedelta(seconds=1)
    record_progress(turn, AgentProgress(str(turn["id"]), 3, "tool_completed", "get_product",
                                       draft=draft, draft_updated=True))
    assert conversations.detail(buyer, cid)["draft_cart"]["items"][0]["price"] is None
    with connection() as c:
        c.execute("UPDATE conversation_turns SET lease_until=%s WHERE id=%s",
                  (now() - timedelta(seconds=1), turn["id"]))
    assert conversations.detail(buyer, cid)["draft_cart"] is None
    replacement = conversations.claim_turn(cid)
    record_progress(turn, AgentProgress(str(turn["id"]), 4, "tool_completed", "scale_recipe",
                                       draft=draft, draft_updated=True))
    assert conversations.detail(buyer, cid)["draft_cart"] is None
    record_progress(replacement, AgentProgress(str(turn["id"]), 1, "tool_completed", "scale_recipe",
                                              draft=draft, draft_updated=True))
    conversations.execute_turn(replacement, service, lambda *args: AgentTurn(text="Continue matching."))
    next_turn = conversations.enqueue(buyer, cid, MessageRequest(text="Can you explain it?", idempotency_key=str(uuid4())))
    assert next_turn["draft_cart"] is not None  # The selected plan survives conversational follow-ups.


def test_completed_tools_carry_server_built_details_and_later_rounds_read_results(
    buyer, service, monkeypatch
):
    cid, _ = queue(buyer)
    recipes = {"recipes": [{"recipe_id": "r1", "version": "1", "title": "Carbonara",
                            "summary": "", "base_servings": 4}],
               "rerank_status": "disabled", "note": ""}

    def runner(actor, history, shared, *, on_progress, ensure_live=None):
        progress = Progress(actor["_turn_id"], on_progress)
        progress.emit("started")
        progress.emit("thinking", round_number=1)
        progress.emit("tool_started", "search_recipes")
        progress.emit("tool_completed", "search_recipes",
                      detail=tool_detail("search_recipes", recipes))
        progress.emit("tool_started", "get_product")
        # A failure never shows a detail, even if one is supplied.
        progress.emit("tool_failed", "get_product", "PRIVATE_ERROR", detail="PRIVATE detail")
        progress.emit("thinking", round_number=2)
        progress.emit("complete")
        return AgentTurn(text="Which recipe?")

    monkeypatch.setattr(agent, "run_turn", runner)
    assert run_once(service)
    events = conversations.detail(buyer, cid)["activity"]["events"]
    assert events[3] == {"sequence": 4, "kind": "tool_completed", "label": "Searching recipes",
                         "detail": "Found 1 recipe: Carbonara"}
    assert [e["label"] for e in events if e["kind"] == "thinking"] == [
        "Thinking", "Reading the results"
    ]
    assert "PRIVATE" not in json.dumps(events)


def test_tool_detail_summarises_only_validated_results():
    plan = {"meal_plan": {"title": "MODEL AUTHORED TITLE", "portions": 200, "ingredients": [
        {"name": "MODEL NAME", "unit": "g", "status": "matched"},
        {"name": "x", "unit": "g", "status": "unresolved"},
        {"name": "y", "unit": "g"},
    ]}, "purchase_authorized": False}
    assert tool_detail("scale_recipe", plan) == (
        "200 portions · 3 ingredients · 1 matched to products · 1 unresolved"
    )
    products = {"products": [{"name": f"Milk {n}"} for n in range(5)]}
    assert tool_detail("search_products", products) == (
        "Found 5 products: Milk 0, Milk 1, Milk 2 +2 more"
    )
    prices = {"mode": "fixture", "products": {
        "a": {"gross": "1.20", "available_sales_quantity": "12"},
        "b": {"gross": None, "available_sales_quantity": "0"},
    }}
    # Fixture price and stock must never read as live supplier data.
    assert tool_detail("check_price_and_availability", prices) == (
        "2 products · 1 priced · 1 in stock · demo fixture data"
    )
    assert tool_detail("check_price_and_availability", prices | {"mode": "live"}).endswith(
        "live supplier data"
    )
    basket = {"policy_outcome": "ready_to_commit",
              "snapshot": {"lines": [{}, {}], "gross_total": "42.10", "currency": "EUR"}}
    assert tool_detail("prepare_order", basket) == (
        "Mock basket · 2 lines · 42.10 EUR · ready for your confirmation"
    )
    assert tool_detail("search_memory", {"items": [{"text": "PRIVATE"}]}) == "1 saved preference"
    assert tool_detail("get_recipe", {"recipe": {}}) is None
    assert tool_detail("search_recipes", "not a dict") is None
    assert tool_detail("search_recipes", {"recipes": None}) == "No matching recipes"
    long = {"products": [{"name": "N" * 300}]}
    assert len(tool_detail("search_products", long)) == 160
