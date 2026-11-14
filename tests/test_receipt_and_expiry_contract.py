"""Expiry, blocked outcomes, receipts and proposal fields (person 3, WS-D).

Covers JNP3-CNF-014, CNF-015, CNF-017, CNF-018 and PRP-002 with exact codes and side effects.
Fixture catalog and invented FixtureClient prices only; every order is the demo service's mock
acceptance.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, PrepareRequest

LABEL = "Accepted by demo order service"


@pytest.fixture
def actor(buyer):
    return auth.internal_agent(buyer)


def prepared(service, actor, data):
    return service.prepare_order(actor, PrepareRequest.model_validate(data))


def body_for(p, key=None, revision=None):
    return CommitRequest(
        proposal_id=p["proposal_id"],
        revision=revision or p["revision"],
        idempotency_key=key or str(uuid4()),
    )


def count(table):
    with connection() as c:
        return c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def failure(fn):
    with pytest.raises(Problem) as error:
        fn()
    return error.value


# --- JNP3-CNF-014: an expired proposal is refused, with no supplier call and no record ------------


def test_confirmation_after_expiry_is_refused_without_side_effects(
    service, connector, buyer, actor, request_data, monkeypatch
):
    p = prepared(service, actor, request_data)
    monkeypatch.setattr(conversations, "now", lambda: p["expires_at"] + timedelta(seconds=1))
    lookups = []
    monkeypatch.setattr(connector, "lookup", lambda *a: lookups.append(a))
    error = failure(lambda: conversations.confirm(buyer, p["proposal_id"], body_for(p), service))
    assert (error.code, error.status) == ("DECISION_CLOSED", 409)
    assert lookups == [] and count("orders") == count("customer_confirmations") == 0


def test_commit_after_expiry_is_refused_before_any_supplier_call(
    service, connector, buyer, actor, request_data, confirm_terms, monkeypatch
):
    p = prepared(service, actor, request_data)
    confirm_terms(p)
    monkeypatch.setattr(workflow, "now", lambda: p["expires_at"] + timedelta(seconds=1))
    lookups = []
    monkeypatch.setattr(connector, "lookup", lambda *a: lookups.append(a))
    assert failure(lambda: service.commit_order(actor, body_for(p))).code == "PROPOSAL_EXPIRED"
    assert lookups == [] and count("orders") == 0


def test_expiry_comes_from_configuration_and_never_exceeds_it(
    service, actor, request_data, monkeypatch
):
    from aimo.config import settings
    from aimo.db import now

    monkeypatch.setattr(settings(), "proposal_ttl_seconds", 120)
    before = now()
    p = prepared(service, actor, request_data)
    assert p["expires_at"] <= before + timedelta(seconds=121)


# --- JNP3-CNF-015: denied and needs_resolution stay blocked whatever the customer confirms -------


@pytest.mark.parametrize("state", ["denied", "needs_resolution"])
def test_blocked_outcomes_cannot_be_confirmed_or_committed(
    state, service, buyer, actor, request_data
):
    if state == "denied":
        request_data["budget_gross"] = "1"
    else:
        request_data["lines"][0]["amount"] = "10000"
    p = prepared(service, actor, request_data)
    assert p["policy_outcome"] == state
    error = failure(lambda: conversations.confirm(buyer, p["proposal_id"], body_for(p), service))
    assert (error.code, error.status) == ("COMMIT_BLOCKED", 409)
    assert failure(lambda: service.commit_order(actor, body_for(p))).code == "COMMIT_BLOCKED"
    assert count("orders") == count("customer_confirmations") == 0


# --- JNP3-CNF-018 and CNF-017: every receipt is labelled mock acceptance and stays retrievable ---


def three_orders(service, buyer, actor, request_data):
    receipts = []
    for _ in range(3):
        p = prepared(service, actor, request_data | {"idempotency_key": str(uuid4())})
        receipts.append(conversations.confirm(buyer, p["proposal_id"], body_for(p), service))
    return receipts


def test_every_receipt_is_labelled_as_mock_acceptance(service, buyer, actor, request_data):
    receipts = three_orders(service, buyer, actor, request_data)
    with connection() as c:
        stored = {str(r["id"]): r["receipt"] for r in c.execute("SELECT id,receipt FROM orders")}
        events = c.execute("SELECT detail FROM audit_events WHERE event='accepted_mock'").fetchall()
    assert len(receipts) == len(stored) == len(events) == 3
    for receipt in receipts:
        assert receipt["label"] == LABEL and receipt["status"] == "accepted_mock"
        assert receipt["order_status"] == "accepted_mock"
        assert receipt["upstream_order_placed"] is False
        assert receipt["inventory_reserved"] is False
        assert stored[receipt["order_id"]] == receipt
        assert service.get_order(actor, receipt["order_id"]) == receipt
    assert {e["detail"]["receipt"]["label"] for e in events} == {LABEL}


def test_receipts_and_audit_history_stay_retrievable_without_expiry(
    service, buyer, actor, request_data, monkeypatch
):
    receipts = three_orders(service, buyer, actor, request_data)
    monkeypatch.setattr(
        workflow, "now", lambda: __import__("aimo.db").db.now() + timedelta(days=400)
    )
    for receipt in receipts:
        assert service.get_order(actor, receipt["order_id"]) == receipt
        current = workflow.get_proposal(buyer, receipt["proposal_id"])
        assert current["order_id"] == receipt["order_id"]
        assert current["order_status"] == "accepted_mock"
        events = [h["event"] for h in current["history"]]
        assert events[0] == "proposal_prepared" and events[-1] == "accepted_mock"
        assert "customer_confirmed" in events
    with connection() as c:  # nothing in the application removes or ages out history
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 3
        assert c.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"] >= 9


# --- JNP3-PRP-002: a proposal carries id, revision, fingerprint, totals, outcome and expiry ------


def test_proposal_response_carries_every_required_field(service, buyer, actor, request_data):
    p = prepared(service, actor, request_data)
    for response in (p, service.get_proposal(actor, p["proposal_id"])):
        assert response["proposal_id"] and response["revision"] == 1
        assert response["snapshot"]["gross_total"] and response["snapshot"]["net_total"]
        assert response["policy_outcome"] and response["expires_at"]
        assert response.get("fingerprint")
