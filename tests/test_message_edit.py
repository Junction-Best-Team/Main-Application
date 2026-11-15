"""Edit a persisted user message: truncate later turns and requeue generation."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aimo import conversations
from aimo.api import create_app
from aimo.chat_schemas import AgentTurn, ConversationCreate, EditMessageRequest, MessageRequest
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


def two_turns(buyer, service):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    first = MessageRequest(text="First ask", idempotency_key=str(uuid4()))
    conversations.message(buyer, cid, first, service, lambda *a: AgentTurn(text="First reply"))
    second = MessageRequest(text="Second ask", idempotency_key=str(uuid4()))
    conversations.message(buyer, cid, second, service, lambda *a: AgentTurn(text="Second reply"))
    data = conversations.detail(buyer, cid)
    assert [m["role"] for m in data["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    return cid, data["messages"][0]["id"], data["messages"]


def test_edit_truncates_later_messages_and_requeues(buyer, service):
    cid, first_id, _ = two_turns(buyer, service)
    edited = conversations.edit_message(
        buyer,
        cid,
        first_id,
        EditMessageRequest(text="Edited first ask", idempotency_key=str(uuid4())),
    )
    assert edited["busy"] is True
    assert [m["role"] for m in edited["messages"]] == ["user"]
    assert edited["messages"][0]["text"] == "Edited first ask"
    assert run_once(service, lambda *a: AgentTurn(text="Fresh reply"))
    final = conversations.detail(buyer, cid)
    assert not final["busy"]
    assert [m["text"] for m in final["messages"]] == ["Edited first ask", "Fresh reply"]


def test_edit_refuses_while_busy(buyer, service):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    body = MessageRequest(text="In flight", idempotency_key=str(uuid4()))
    queued = conversations.enqueue(buyer, cid, body)
    assert queued["busy"]
    message_id = queued["messages"][0]["id"]
    with pytest.raises(Problem) as err:
        conversations.edit_message(
            buyer,
            cid,
            message_id,
            EditMessageRequest(text="Nope", idempotency_key=str(uuid4())),
        )
    assert err.value.code == "CONVERSATION_BUSY"


def test_edit_refuses_non_user_messages(buyer, service):
    cid, first_id, messages = two_turns(buyer, service)
    assistant_id = messages[1]["id"]
    with pytest.raises(Problem) as err:
        conversations.edit_message(
            buyer,
            cid,
            assistant_id,
            EditMessageRequest(text="Cannot edit Aimo", idempotency_key=str(uuid4())),
        )
    assert err.value.code == "MESSAGE_NOT_EDITABLE"
    assert conversations.detail(buyer, cid)["messages"][0]["id"] == first_id


def test_edit_idempotent_retry_does_not_fork(buyer, service):
    cid, first_id, _ = two_turns(buyer, service)
    key = str(uuid4())
    body = EditMessageRequest(text="Same edit", idempotency_key=key)
    first = conversations.edit_message(buyer, cid, first_id, body)
    assert first["busy"] is True
    second = conversations.edit_message(buyer, cid, first_id, body)
    assert second["busy"] is True
    assert [m["id"] for m in second["messages"]] == [m["id"] for m in first["messages"]]
    assert run_once(service, lambda *a: AgentTurn(text="Once"))
    third = conversations.edit_message(buyer, cid, first_id, body)
    assert not third["busy"]
    assert [m["text"] for m in third["messages"]] == ["Same edit", "Once"]
    with pytest.raises(Problem) as err:
        conversations.edit_message(
            buyer,
            cid,
            first_id,
            EditMessageRequest(text="Different text", idempotency_key=key),
        )
    assert err.value.code == "IDEMPOTENCY_CONFLICT"


def test_edit_over_http_needs_csrf_and_returns_truncated_conversation(service):
    with TestClient(create_app(service)) as client:
        headers = signed(client)
        cid = client.post(
            "/api/conversations",
            headers=headers,
            json={"idempotency_key": str(uuid4())},
        ).json()["id"]

        def runner(*args):
            return AgentTurn(text="ok")

        from aimo.worker import run_once as once

        key1 = str(uuid4())
        assert (
            client.post(
                f"/api/conversations/{cid}/messages",
                headers=headers,
                json={"text": "One", "idempotency_key": key1},
            ).status_code
            == 200
        )
        assert once(service, runner)
        key2 = str(uuid4())
        assert (
            client.post(
                f"/api/conversations/{cid}/messages",
                headers=headers,
                json={"text": "Two", "idempotency_key": key2},
            ).status_code
            == 200
        )
        assert once(service, runner)
        messages = client.get(f"/api/conversations/{cid}").json()["messages"]
        first_id = messages[0]["id"]
        url = f"/api/conversations/{cid}/messages/{first_id}/edit"
        bare = client.post(url, json={"text": "Edited", "idempotency_key": str(uuid4())})
        assert bare.status_code == 403
        edited = client.post(
            url,
            headers=headers,
            json={"text": "Edited", "idempotency_key": str(uuid4())},
        )
        assert edited.status_code == 200, edited.text
        data = edited.json()
        assert data["busy"] is True
        assert [m["text"] for m in data["messages"]] == ["Edited"]
