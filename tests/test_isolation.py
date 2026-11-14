"""JNP3-SEC-001/002: a second real buyer cannot read or act on the first buyer's records.

Buyer A is demo-hotel (seeded). Buyer B is created by wsc_support.add_second_buyer with its own
policy, approver, legacy agent and internal agent. Fixture mode only; no supplier calls.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wsc_support import add_second_buyer, counts, login_headers

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.api import create_app
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest
from aimo.db import Problem
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest

OTHER_PASSWORD = "other-test-password-only"


@pytest.fixture
def world(service, buyer, agent, request_data):
    """Buyer A has a conversation, a prepared+confirmed purchase (order) and a pending approval."""
    other = add_second_buyer()
    internal_a = auth.internal_agent(buyer)
    confirmed = service.prepare_order(internal_a, PrepareRequest.model_validate(request_data))
    confirm_body = CommitRequest(
        proposal_id=confirmed["proposal_id"], revision=1, idempotency_key=str(uuid4())
    )
    receipt = conversations.confirm(buyer, confirmed["proposal_id"], confirm_body, service)
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]

    def runner(actor, history, shared):
        return AgentTurn(text="Review this basket.", proposal_id=confirmed["proposal_id"])

    conversations.message(
        buyer,
        cid,
        MessageRequest(text="Need ingredients.", idempotency_key=str(uuid4())),
        service,
        runner,
    )
    pending_request = dict(request_data, idempotency_key=str(uuid4()))
    pending_request["lines"] = [{"product_id": "464398", "amount": "10", "unit": "L"}]
    pending = service.prepare_order(internal_a, PrepareRequest.model_validate(pending_request))
    assert pending["policy_outcome"] == "approval_required" and pending["approval_id"]
    return {
        "other": other,
        "cid": cid,
        "proposal": confirmed,
        "order_id": receipt["order_id"],
        "confirm_body": confirm_body,
        "pending": pending,
        "request_data": request_data,
    }


def expect_not_found(fn):
    with pytest.raises(Problem) as error:
        fn()
    assert error.value.status == 404, (error.value.code, error.value.status)
    assert error.value.code in ("NOT_FOUND",), error.value.code


def test_second_buyer_cannot_read_or_act_on_first_buyers_records(service, world):
    other, pid = world["other"], world["proposal"]["proposal_id"]
    approval_id = world["pending"]["approval_id"]
    before = counts()
    for who in (other["approver"], other["agent"], other["internal"]):
        expect_not_found(lambda who=who: service.get_proposal(who, pid))
        expect_not_found(lambda who=who: service.get_order(who, world["order_id"]))
        expect_not_found(lambda who=who: service.commit_order(who, world["confirm_body"]))
        expect_not_found(
            lambda who=who: service.commit_order(
                who,
                CommitRequest(
                    proposal_id=world["pending"]["proposal_id"],
                    revision=1,
                    idempotency_key=str(uuid4()),
                ),
            )
        )
    human = other["approver"]
    expect_not_found(lambda: workflow.get_proposal(human, pid))
    expect_not_found(lambda: workflow.get_order(human, world["order_id"]))
    expect_not_found(lambda: workflow.approval_detail(human, approval_id))
    expect_not_found(
        lambda: workflow.record_human_decision(
            human, approval_id, DecisionRequest(revision=1, decision="approve")
        )
    )
    expect_not_found(lambda: conversations.detail(human, world["cid"]))
    expect_not_found(
        lambda: conversations.enqueue(
            human, world["cid"], MessageRequest(text="hi there", idempotency_key=str(uuid4()))
        )
    )
    # Reusing buyer A's own confirmation key and payload must not return A's receipt.
    expect_not_found(
        lambda: conversations.confirm(human, pid, world["confirm_body"], service)
    )
    assert workflow.list_approvals(human)["items"] == []
    assert conversations.listing(human, 0, 20)["items"] == []
    assert conversations.purchases(human, 0, 20)["items"] == []
    assert counts() == before


def test_same_preparation_key_creates_a_separate_proposal_per_buyer(service, world):
    other = world["other"]
    request = PrepareRequest.model_validate(world["request_data"])
    mine = service.prepare_order(other["agent"], request)
    assert mine["buyer_id"] == "other"
    assert mine["proposal_id"] != world["proposal"]["proposal_id"]
    assert service.prepare_order(other["agent"], request)["proposal_id"] == mine["proposal_id"]


def test_identity_naming_another_buyer_is_rejected(service, buyer, world):
    other = world["other"]
    pid = world["proposal"]["proposal_id"]
    forged_human = dict(other["approver"]) | {"buyer_id": "demo-hotel"}
    forged_agent = dict(other["agent"]) | {"buyer_id": "demo-hotel"}
    reversed_human = dict(buyer) | {"buyer_id": "other"}
    before = counts()
    for forged in (forged_human, forged_agent, reversed_human):
        for call in (
            lambda f=forged: service.get_proposal(f, pid),
            lambda f=forged: service.get_order(f, world["order_id"]),
            lambda f=forged: service.get_purchase_policy(f),
            lambda f=forged: service.prepare_order(
                f, PrepareRequest.model_validate(world["request_data"])
            ),
            lambda f=forged: conversations.detail(f, world["cid"]),
        ):
            with pytest.raises(Problem) as error:
                call()
            # workflow.get_proposal looks the proposal up before it validates the identity, so a
            # forged buyer_id may answer 404 instead of 403; either way no data is returned.
            assert (error.value.code, error.value.status) in (
                ("AUTHORITY_REVOKED", 403),
                ("NOT_FOUND", 404),
            )
    assert counts() == before


def test_second_buyer_over_http_sees_nothing_of_the_first(service, world):
    cid, pid = world["cid"], world["proposal"]["proposal_id"]
    approval_id = world["pending"]["approval_id"]
    before = counts()
    with TestClient(create_app(service)) as client:
        headers = login_headers(client, "other-buyer", OTHER_PASSWORD)
        assert client.get("/api/session").json()["buyer_id"] == "other"
        assert client.get("/api/conversations").json()["items"] == []
        assert client.get("/api/purchases").json()["items"] == []
        assert client.get("/api/approvals").json()["items"] == []
        assert client.get(f"/api/conversations/{cid}").status_code == 404
        assert client.get(f"/api/conversations/{cid}/events").status_code == 404
        assert client.get(f"/api/purchases/{pid}").status_code == 404
        assert client.get(f"/api/approvals/{approval_id}").status_code == 404
        message = {"text": "hello there", "idempotency_key": str(uuid4())}
        assert (
            client.post(f"/api/conversations/{cid}/messages", headers=headers, json=message)
        ).status_code == 404
        confirm = {"proposal_id": pid, "revision": 1, "idempotency_key": str(uuid4())}
        assert (
            client.post(f"/api/purchases/{pid}/confirm", headers=headers, json=confirm)
        ).status_code == 404
        decision = {"revision": 1, "decision": "approve"}
        assert (
            client.post(f"/api/approvals/{approval_id}/decision", headers=headers, json=decision)
        ).status_code == 404
    assert counts() == before
