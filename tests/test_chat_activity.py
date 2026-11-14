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
from aimo.chat_activity import TOOL_LABELS, record_progress
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

    def runner(actor, history, shared, *, on_progress):
        progress = Progress(actor["_turn_id"], on_progress)
        progress.emit("started")
        for tool in ("search_recipes", "get_recipe", "search_products", "get_product"):
            progress.emit("tool_started", tool)
            live = conversations.detail(buyer, cid)
            assert live["busy"] and live["activity"]["events"][-1]["kind"] == "tool_started"
            progress.emit("tool_completed", tool)
        # Unknown/model-supplied names and error details must never reach the browser.
        progress.emit("tool_started", "private-unknown-tool-name")
        progress.emit("tool_failed", "private-unknown-tool-name", "PRIVATE_ERROR_DETAIL")
        progress.emit("complete")
        return AgentTurn(text="What date?")

    monkeypatch.setattr(agent, "run_turn", runner)
    assert run_once(service)
    result = conversations.detail(buyer, cid)
    events = result["activity"]["events"]
    assert result["activity"]["state"] == "complete" and not result["busy"]
    assert [e["sequence"] for e in events] == list(range(1, 13))
    assert events[1]["label"] == "Searching recipes"
    assert events[5]["label"] == "Searching products"
    assert events[-2] == {"sequence": 11, "kind": "tool_failed", "label": "Using a tool"}
    assert "PRIVATE" not in json.dumps(events) and "private-unknown" not in json.dumps(events)
    close_pools()
    assert conversations.detail(buyer, cid) == result
    assert conversations.enqueue(buyer, cid, body) == result  # Retry adds no duplicate activity.
    assert not run_once(service)
    next_body = MessageRequest(text="Next lunch", idempotency_key=str(uuid4()))
    # A new turn in this conversation starts empty and does not borrow the old activity.
    next_turn = conversations.enqueue(buyer, cid, next_body)
    assert next_turn["activity"]["events"] == []


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

    def fail(actor, history, shared, *, on_progress):
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
    data = json.loads(response.text.split("data: ")[1].split("\n")[0])
    assert data["busy"] and data["activity"]["events"][0]["label"] == "Searching recipes"
    assert response.headers["x-accel-buffering"] == "no"


def test_all_registered_tools_have_product_activity_labels(service):
    session = ToolSession({"_turn_id": str(uuid4())}, service)
    assert set(session.registry) == set(TOOL_LABELS)
