import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aimo import auth, conversations
from aimo.api import create_app
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest
from aimo.db import Problem, close_pools, connection, now
from aimo.schemas import CommitRequest, PrepareRequest


def signed(client):
    result = client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert result.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": result.json()["csrf_token"]}


def test_conversation_persists_retry_and_cannot_choose_identity(service, buyer, request_data):
    app = create_app(service)
    calls = []

    def runner(actor, history, shared):
        assert actor["role"] == "agent" and actor["buyer_id"] == buyer["buyer_id"]
        assert actor["id"] != buyer["id"]
        calls.append(actor["_turn_id"])
        p = shared.prepare_order(actor, PrepareRequest.model_validate(request_data))
        return AgentTurn(text="Review this verified basket.", proposal_id=p["proposal_id"])

    with TestClient(app) as client:
        assert client.get("/api/conversations").status_code == 401
        headers = signed(client)
        data = {"title": "Carbonara", "idempotency_key": str(uuid4())}
        created = client.post("/api/conversations", headers=headers, json=data)
        assert created.status_code == 200, created.text
        cid = created.json()["id"]
        assert client.post("/api/conversations", headers=headers, json=data).json()["id"] == cid
        url = f"/api/conversations/{cid}/messages"
        body = {
            "text": "I need ingredients for 200 portions of carbonara.",
            "idempotency_key": str(uuid4()),
        }
        assert client.post(url, json=body).status_code == 403
        assert (
            client.post(url, headers=headers, json=body | {"identity": buyer["id"]}).status_code
            == 422
        )
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["busy"] is True and calls == []
        from aimo.worker import run_once

        assert run_once(service, runner)
        response = client.get(f"/api/conversations/{cid}")
        assert len(response.json()["messages"]) == 2 and len(response.json()["purchases"]) == 1
        assert client.post(url, headers=headers, json=body).json() == response.json()
        assert len(calls) == 1
        assert (
            client.post(url, headers=headers, json=body | {"text": "different"}).status_code == 409
        )
        close_pools()  # New app/pool simulates restart of in-memory process state.
        with TestClient(create_app(service)) as restarted:
            restarted.cookies.update(client.cookies)
            assert restarted.get(f"/api/conversations/{cid}").json() == response.json()
        assert (
            client.get("/api/purchases").json()["items"][0]["proposal_id"]
            == response.json()["purchases"][0]["proposal_id"]
        )


def test_failed_turn_resumes_same_key_and_concurrent_message_is_bounded(service, buyer):
    c = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))
    cid, body = c["id"], MessageRequest(text="carbonara", idempotency_key=str(uuid4()))
    entered, release = Event(), Event()

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        raise Problem("PROVIDER_FAILED", "Retry this message", 503)

    with ThreadPoolExecutor() as executor:
        pending = executor.submit(conversations.message, buyer, cid, body, service, blocked)
        assert entered.wait(5)
        with pytest.raises(Problem, match="in progress"):
            conversations.message(buyer, cid, body, service, blocked)
        release.set()
        with pytest.raises(Problem, match="Retry this message"):
            pending.result()
    with pytest.raises(Problem, match="previous message"):
        conversations.message(
            buyer, cid, MessageRequest(text="next", idempotency_key=str(uuid4())), service, blocked
        )
    result = conversations.message(
        buyer, cid, body, service, lambda *args: AgentTurn(text="What delivery date?")
    )
    assert [m["role"] for m in result["messages"]] == ["user", "assistant"]


def test_internal_confirmation_cannot_be_fabricated_and_retry_survives_restart(
    service, buyer, request_data, connector
):
    actor = auth.internal_agent(buyer)
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    payload = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    with pytest.raises(Problem) as err:
        service.commit_order(actor, payload)
    assert err.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"
    receipt = conversations.confirm(buyer, p["proposal_id"], payload, service)
    assert receipt["status"] == "accepted_mock" and receipt["upstream_order_placed"] is False
    close_pools()
    connector.lookup = lambda *args: (_ for _ in ()).throw(AssertionError("no upstream retry"))
    assert conversations.confirm(buyer, p["proposal_id"], payload, service) == receipt
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 1
        assert (
            c.execute(
                "SELECT count(*) AS n FROM audit_events WHERE event='customer_confirmed'"
            ).fetchone()["n"]
            == 1
        )


def test_repricing_requires_another_explicit_confirmation(service, buyer, request_data, connector):
    actor = auth.internal_agent(buyer)
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    payload = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    connector.price_multiplier = Decimal("1.1")
    revised = conversations.confirm(buyer, p["proposal_id"], payload, service)
    assert revised["status"] == "revised" and revised["revision"] == 2
    with pytest.raises(Problem) as err:
        service.commit_order(actor, payload.model_copy(update={"revision": 2}))
    assert err.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"
    with pytest.raises(Problem) as err:
        conversations.confirm(buyer, p["proposal_id"], payload, service)
    assert err.value.code == "STALE_REVISION"
    with pytest.raises(Problem) as err:
        conversations.confirm(
            buyer, p["proposal_id"], payload.model_copy(update={"revision": 2}), service
        )
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    receipt = conversations.confirm(
        buyer,
        p["proposal_id"],
        payload.model_copy(update={"revision": 2, "idempotency_key": str(uuid4())}),
        service,
    )
    assert receipt["revision"] == 2


def test_other_account_cannot_read_conversation_or_confirm(service, buyer, agent, request_data):
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    # Scoped lookup occurs before proposal/message data can be returned.
    other = buyer | {"buyer_id": "nonexistent"}
    with connection() as c:
        with pytest.raises(Problem) as err:
            conversations.owned(c, other, cid)
    assert err.value.status == 404
    with connection() as c:
        with pytest.raises(Problem) as err:
            from aimo.approval_workflow import proposal

            proposal(c, p["proposal_id"], other)
    assert err.value.status == 404


def test_expired_turn_can_resume_without_duplicate_user_message(service, buyer):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    body = MessageRequest(text="hello", idempotency_key=str(uuid4()))

    def interrupted(*args):
        raise Problem("RETRY", "retry")

    with pytest.raises(Problem):
        conversations.message(buyer, cid, body, service, interrupted)
    with connection() as c:
        c.execute(
            "UPDATE conversation_turns SET state='running',lease_until=%s",
            (now() - timedelta(seconds=1),),
        )
    result = conversations.message(
        buyer, cid, body, service, lambda *args: AgentTurn(text="hello back")
    )
    assert len(result["messages"]) == 2


@pytest.mark.parametrize("state", ["expired", "rejected", "denied", "needs_resolution"])
def test_confirmation_preserves_blocked_states(state, service, buyer, request_data, monkeypatch):
    from aimo import approval_workflow as workflow
    from aimo.schemas import DecisionRequest

    actor = auth.internal_agent(buyer)
    if state == "denied":
        request_data["budget_gross"] = "1"
    if state == "needs_resolution":
        request_data["lines"][0]["amount"] = "10000"
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    if state == "rejected":
        workflow.record_human_decision(
            buyer, p["approval_id"], DecisionRequest(revision=1, decision="reject")
        )
    if state == "expired":
        monkeypatch.setattr(conversations, "now", lambda: p["expires_at"] + timedelta(seconds=1))
    with pytest.raises(Problem) as err:
        conversations.confirm(buyer, p["proposal_id"], body, service)
    assert err.value.code in ("COMMIT_BLOCKED", "DECISION_CLOSED")
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 0


def test_another_authorized_customer_can_resume_after_original_authority_revoked(
    service, buyer, request_data, monkeypatch
):
    from aimo.db import js

    actor = auth.internal_agent(buyer)
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    first = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    original_commit = service.commit_order

    def unavailable(*args):
        raise Problem("SUPPLIER_UNAVAILABLE", "Retry after supplier recovers", 503)

    monkeypatch.setattr(service, "commit_order", unavailable)
    with pytest.raises(Problem):
        conversations.confirm(buyer, p["proposal_id"], first, service)
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (buyer["buyer_id"],))
        c.execute("UPDATE identities SET active=false WHERE id='buyer'")
        c.execute(
            "INSERT INTO identities VALUES('second-buyer','demo-hotel','approver',true,'unused',%s)",
            (js(buyer["authority"]),),
        )
        second_buyer = c.execute("SELECT * FROM identities WHERE id='second-buyer'").fetchone()
    monkeypatch.setattr(service, "commit_order", original_commit)
    second = first.model_copy(update={"idempotency_key": str(uuid4())})
    receipt = conversations.confirm(second_buyer, p["proposal_id"], second, service)
    assert receipt["status"] == "accepted_mock"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 2
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 1


def test_retry_recovers_preparation_saved_before_interrupted_assistant_reply(
    service, buyer, request_data
):
    from aimo.db import fingerprint

    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    body = MessageRequest(text="Prepare my basket", idempotency_key=str(uuid4()))

    def interrupted(actor, history, shared):
        prepared = PrepareRequest.model_validate(
            request_data
            | {
                "idempotency_key": "chat-" + fingerprint({"turn": actor["_turn_id"]}),
            }
        )
        shared.prepare_order(actor, prepared)
        raise Problem("INTERRUPTED", "Response stopped after preparation", 503)

    with pytest.raises(Problem):
        conversations.message(buyer, cid, body, service, interrupted)

    def must_not_call_provider(*args):
        raise AssertionError("A saved preparation must recover without provider access")

    recovered = conversations.message(buyer, cid, body, service, must_not_call_provider)
    assert len(recovered["messages"]) == 2 and len(recovered["purchases"]) == 1
    assert "recovered" in recovered["messages"][-1]["text"]
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
