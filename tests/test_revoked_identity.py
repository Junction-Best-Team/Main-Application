"""JNP3-SEC-003: a revoked identity is refused at every tool and confirmation entry point.

"Revoked" means identities.active=false or a changed role (the same state context() checks).
Each refusal must also write nothing and never reach the supplier connector.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wsc_support import counts, login_headers

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.api import create_app
from aimo.chat_schemas import ConversationCreate, MessageRequest
from aimo.db import Problem, connection
from aimo.schemas import (
    CommitRequest,
    DecisionRequest,
    LookupRequest,
    PrepareRequest,
    SearchRequest,
)

TOOLS = [
    "search_products",
    "get_product",
    "get_purchase_policy",
    "check_price_and_availability",
    "prepare_order",
    "get_proposal",
    "get_order",
    "commit_order",
]


def revoke(identity_id, change, swapped_role="approver"):
    """inactive: deactivated; role: the identity no longer holds the role the caller claims."""
    with connection() as c:
        if change == "inactive":
            c.execute("UPDATE identities SET active=false WHERE id=%s", (identity_id,))
        else:
            c.execute("UPDATE identities SET role=%s WHERE id=%s", (swapped_role, identity_id))


def forbid_supplier(connector):
    def fail(*args, **kwargs):
        raise AssertionError("a revoked identity must never reach the supplier connector")

    connector.lookup = fail


@pytest.mark.parametrize("change", ["inactive", "role"])
@pytest.mark.parametrize("tool", TOOLS)
def test_revoked_agent_is_refused_by_every_tool(
    tool, change, service, agent, request_data, connector, confirm_terms
):
    prepared = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    confirm_terms(prepared)  # every agent commit needs the customer's recorded confirmation
    receipt = service.commit_order(
        agent,
        CommitRequest(
            proposal_id=prepared["proposal_id"], revision=1, idempotency_key=str(uuid4())
        ),
    )
    second = service.prepare_order(
        agent, PrepareRequest.model_validate(dict(request_data, idempotency_key=str(uuid4())))
    )
    revoke(agent["id"], change)
    forbid_supplier(connector)
    before = counts()
    calls = {
        "search_products": lambda: service.search_products(agent, SearchRequest(query="milk")),
        "get_product": lambda: service.get_product(agent, "464306"),
        "get_purchase_policy": lambda: service.get_purchase_policy(agent),
        "check_price_and_availability": lambda: service.check_price_and_availability(
            agent,
            LookupRequest(product_ids=["464306"], delivery_date=date.today() + timedelta(days=2)),
        ),
        "prepare_order": lambda: service.prepare_order(
            agent, PrepareRequest.model_validate(dict(request_data, idempotency_key=str(uuid4())))
        ),
        "get_proposal": lambda: service.get_proposal(agent, prepared["proposal_id"]),
        "get_order": lambda: service.get_order(agent, receipt["order_id"]),
        "commit_order": lambda: service.commit_order(
            agent,
            CommitRequest(
                proposal_id=second["proposal_id"], revision=1, idempotency_key=str(uuid4())
            ),
        ),
    }
    with pytest.raises(Problem) as error:
        calls[tool]()
    assert (error.value.code, error.value.status) == ("AUTHORITY_REVOKED", 403)
    assert counts() == before


def test_revoked_internal_agent_cannot_be_resolved_for_a_turn(buyer):
    internal = auth.internal_agent(buyer)
    revoke(internal["id"], "inactive")
    with pytest.raises(Problem) as error:
        auth.internal_agent(buyer)
    assert (error.value.code, error.value.status) == ("AGENT_NOT_CONFIGURED", 503)


def test_confirmation_is_refused_when_the_internal_agent_is_revoked(service, buyer, request_data):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    revoke(internal["id"], "inactive")
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    with pytest.raises(Problem) as error:
        conversations.confirm(buyer, p["proposal_id"], body, service)
    assert error.value.code == "AUTHORITY_REVOKED"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


@pytest.mark.parametrize("change", ["inactive", "role"])
def test_revoked_human_is_refused_everywhere(change, service, buyer, request_data, connector):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    revoke(buyer["id"], change, swapped_role="agent")
    forbid_supplier(connector)
    before = counts()
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    calls = [
        lambda: conversations.confirm(buyer, p["proposal_id"], body, service),
        lambda: workflow.record_human_decision(
            buyer,
            p["approval_id"] or str(uuid4()),
            DecisionRequest(revision=1, decision="approve"),
        ),
        lambda: workflow.list_approvals(buyer),
        lambda: workflow.get_proposal(buyer, p["proposal_id"]),
        lambda: workflow.approval_detail(buyer, p["approval_id"] or str(uuid4())),
        lambda: workflow.get_order(buyer, str(uuid4())),
        lambda: conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4()))),
        lambda: conversations.listing(buyer, 0, 20),
        lambda: conversations.detail(buyer, cid),
        lambda: conversations.purchases(buyer, 0, 20),
        lambda: conversations.enqueue(
            buyer, cid, MessageRequest(text="hello there", idempotency_key=str(uuid4()))
        ),
    ]
    for call in calls:
        with pytest.raises(Problem) as error:
            call()
        assert (error.value.code, error.value.status) in (
            ("AUTHORITY_REVOKED", 403),
            ("NOT_FOUND", 404),  # lookup that precedes the identity check; no data returned
        )
    assert counts() == before


def test_valid_cookie_stops_working_when_the_human_is_revoked(service, buyer, request_data):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    with TestClient(create_app(service)) as client:
        headers = login_headers(client)
        assert client.get("/api/session").status_code == 200
        revoke(buyer["id"], "inactive")
        before = counts()
        assert client.get("/api/session").status_code == 401
        assert client.get("/api/purchases").status_code == 401
        assert client.get("/api/conversations").status_code == 401
        assert client.get("/api/approvals").status_code == 401
        confirm = {"proposal_id": p["proposal_id"], "revision": 1, "idempotency_key": str(uuid4())}
        assert (
            client.post(f"/api/purchases/{p['proposal_id']}/confirm", headers=headers, json=confirm)
        ).status_code == 401
        assert counts() == before
