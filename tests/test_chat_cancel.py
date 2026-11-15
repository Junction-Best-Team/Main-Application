"""Buyer interrupt of a busy chat turn: queued and running cancel + worker fence."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aimo import conversations
from aimo.api import create_app
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest
from aimo.db import Problem
from aimo.worker import run_once


def signed(client):
    result = client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert result.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": result.json()["csrf_token"]}


def queued(buyer):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    body = MessageRequest(text="Plan lunch for cancel", idempotency_key=str(uuid4()))
    data = conversations.enqueue(buyer, cid, body)
    assert data["busy"]
    return cid, body


def test_cancel_queued_turn_clears_busy_and_exposes_retry(buyer):
    cid, body = queued(buyer)
    data = conversations.cancel_turn(buyer, cid)
    assert not data["busy"]
    assert data["retry_message"]["idempotency_key"] == body.idempotency_key
    assert data["retry_message"]["text"] == body.text
    assert conversations.claim_turn(cid) is None


def test_cancel_before_execute_rejects_claim(buyer, service):
    cid, body = queued(buyer)
    turn = conversations.claim_turn(cid)
    assert turn and turn["state"] == "running"
    data = conversations.cancel_turn(buyer, cid)
    assert not data["busy"]
    assert data["retry_message"]["idempotency_key"] == body.idempotency_key
    with pytest.raises(Problem) as error:
        conversations.execute_turn(turn, service, lambda *args: AgentTurn(text="too late"))
    assert error.value.code == "TURN_REPLACED"
    assert not conversations.detail(buyer, cid)["busy"]
    assert conversations.detail(buyer, cid)["retry_message"]["text"] == body.text


def test_cancel_during_execute_blocks_assistant_reply(buyer, service):
    cid, body = queued(buyer)
    turn = conversations.claim_turn(cid)
    entered = Event()
    release = Event()

    def runner(actor, history, shared):
        entered.set()
        assert release.wait(5)
        return AgentTurn(text="should not publish")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(conversations.execute_turn, turn, service, runner)
        assert entered.wait(5)
        conversations.cancel_turn(buyer, cid)
        release.set()
        with pytest.raises(Problem) as error:
            future.result(timeout=5)
    assert error.value.code == "TURN_REPLACED"
    data = conversations.detail(buyer, cid)
    assert not data["busy"]
    assert data["retry_message"]["idempotency_key"] == body.idempotency_key
    assert all(m["role"] != "assistant" for m in data["messages"])


def test_ensure_attempt_raises_after_cancel(buyer):
    cid, _ = queued(buyer)
    turn = conversations.claim_turn(cid)
    conversations.cancel_turn(buyer, cid)
    with pytest.raises(Problem) as error:
        conversations.ensure_attempt(turn)
    assert error.value.code == "TURN_REPLACED"


def test_cancel_is_idempotent_when_idle(buyer):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    first = conversations.cancel_turn(buyer, cid)
    second = conversations.cancel_turn(buyer, cid)
    assert not first["busy"] and not second["busy"]
    assert first["retry_message"] is None and second["retry_message"] is None


def test_cancel_over_http_needs_csrf_and_returns_retry(service):
    with TestClient(create_app(service)) as client:
        headers = signed(client)
        cid = client.post(
            "/api/conversations",
            headers=headers,
            json={"idempotency_key": str(uuid4())},
        ).json()["id"]
        key = str(uuid4())
        busy = client.post(
            f"/api/conversations/{cid}/messages",
            headers=headers,
            json={"text": "Stop this please", "idempotency_key": key},
        )
        assert busy.status_code == 200 and busy.json()["busy"]
        bare = client.post(f"/api/conversations/{cid}/cancel")
        assert bare.status_code == 403
        cancelled = client.post(f"/api/conversations/{cid}/cancel", headers=headers)
        assert cancelled.status_code == 200
        data = cancelled.json()
        assert not data["busy"]
        assert data["retry_message"]["idempotency_key"] == key
        assert not run_once(service, lambda *args: AgentTurn(text="should not run"))
