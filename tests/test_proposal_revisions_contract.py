"""Contract tests for proposal revisions and accepted substitutions (person 3, WS-D).

JNP3-PRP-003 (Approved): a supplier price or availability change gives a new revision of the
same proposal; a customer quantity change gives a new proposal. JNP3-PRP-007 (Approved, Q-41): a
substitution the customer accepts is accepted by confirming the revision that contains it.
Everything runs against the authored fixture catalog and the invented FixtureClient responses:
nothing here is live supplier data, and the orders are the demo order service's mock acceptance.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, PrepareRequest


@pytest.fixture
def actor(buyer):
    return auth.internal_agent(buyer)


def body_for(p, key=None, revision=None):
    return CommitRequest(
        proposal_id=p["proposal_id"],
        revision=revision or p["revision"],
        idempotency_key=key or str(uuid4()),
    )


def rows(sql, args=()):
    with connection() as c:
        return c.execute(sql, args).fetchall()


def revisions_of(proposal_id):
    return rows(
        "SELECT revision,fingerprint,snapshot FROM proposal_revisions "
        "WHERE proposal_id=%s ORDER BY revision",
        (proposal_id,),
    )


# --- JNP3-PRP-003: a supplier change revises the same proposal ------------------------------------


def assert_same_proposal_new_revision(p, revised, buyer):
    assert revised["status"] == "revised" and revised["revision"] == 2
    assert revised["proposal_id"] == p["proposal_id"]  # the same proposal, not a new one
    old, new = revisions_of(p["proposal_id"])
    assert (old["revision"], new["revision"]) == (1, 2)
    assert old["fingerprint"] != new["fingerprint"]  # the new revision's terms differ
    assert old["snapshot"] != new["snapshot"]
    assert old["snapshot"]["gross_total"] == p["snapshot"]["gross_total"]  # revision 1 is intact
    assert len(rows("SELECT id FROM proposals")) == 1
    assert rows("SELECT order_id FROM proposals")[0]["order_id"] is None
    assert rows("SELECT count(*) AS n FROM orders")[0]["n"] == 0
    # The old revision stays readable through its own approval, the current one through the proposal.
    if p["approval_id"]:
        assert workflow.approval_detail(buyer, p["approval_id"])["revision"] == 1
    assert workflow.get_proposal(buyer, p["proposal_id"])["revision"] == 2


def test_a_supplier_price_change_at_commit_revises_the_same_proposal(
    service, connector, buyer, actor, request_data
):
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    connector.price_multiplier = Decimal("1.1")
    revised = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert_same_proposal_new_revision(p, revised, buyer)
    old, new = revisions_of(p["proposal_id"])
    assert Decimal(new["snapshot"]["gross_total"]) > Decimal(old["snapshot"]["gross_total"])


def test_a_supplier_availability_change_at_commit_revises_the_same_proposal(
    service, connector, buyer, actor, request_data
):
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    connector.stock["464306"] = "4"  # fewer than the 10 L requested
    revised = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert_same_proposal_new_revision(p, revised, buyer)


def test_a_supplier_change_commits_through_the_agent_path_as_a_revision_too(
    service, connector, buyer, actor, request_data, confirm_terms
):
    """Same rule for a commit by the internal agent after a recorded confirmation."""
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    confirm_terms(p)
    connector.price_multiplier = Decimal("1.1")
    revised = service.commit_order(actor, body_for(p))
    assert_same_proposal_new_revision(p, revised, buyer)


# --- JNP3-PRP-003: a customer quantity change is a new proposal -----------------------------------


def with_amount(data, amount, key=None):
    line = data["lines"][0] | {"amount": amount}
    return PrepareRequest.model_validate(
        data | {"lines": [line], "idempotency_key": key or str(uuid4())}
    )


def test_a_changed_quantity_under_a_new_key_is_a_different_proposal(
    service, buyer, actor, request_data
):
    first = service.prepare_order(actor, with_amount(request_data, "10"))
    second = service.prepare_order(actor, with_amount(request_data, "20"))
    assert second["proposal_id"] != first["proposal_id"] and second["revision"] == 1
    assert len(rows("SELECT id FROM proposals")) == 2
    assert [len(revisions_of(x["proposal_id"])) for x in (first, second)] == [1, 1]
    # The first proposal is untouched by the second.
    assert workflow.get_proposal(buyer, first["proposal_id"])["revision"] == 1


def test_a_changed_quantity_under_the_same_key_is_an_idempotency_conflict(
    service, actor, request_data
):
    key = str(uuid4())
    first = service.prepare_order(actor, with_amount(request_data, "10", key))
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, with_amount(request_data, "20", key))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert len(rows("SELECT id FROM proposals")) == 1
    assert len(revisions_of(first["proposal_id"])) == 1  # never revised in place
    again = service.prepare_order(actor, with_amount(request_data, "10", key))
    assert again["proposal_id"] == first["proposal_id"]  # the unchanged retry replays


# --- JNP3-PRP-007 (Approved, owner Q-41): confirming the revision that holds the substitute -------
# accepts it. There is no separate record: the acceptance is the customer's confirmation, bound
# to the revision and fingerprint that contain the substitute line and its exception.


def test_confirming_the_revision_with_a_substitute_accepts_it(service, buyer, actor, mission):
    p = service.prepare_order(actor, mission)
    # The revision carries the substitute line and the substitution exception.
    assert [x["substitutes_for"] for x in p["request"]["lines"]] == [None, "464306"]
    assert [x["product_id"] for x in p["snapshot"]["lines"]] == ["464306", "464398"]
    (stored,) = rows("SELECT revision,fingerprint,required_exceptions FROM proposal_revisions")
    assert "substitution" in stored["required_exceptions"]
    receipt = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    # The customer's confirmation, the exception approval and the order bind that same revision.
    (confirmation,) = rows("SELECT revision,fingerprint,actor_id FROM customer_confirmations")
    (approval,) = rows("SELECT revision,fingerprint,status,actor_id FROM approvals")
    assert confirmation["revision"] == approval["revision"] == receipt["revision"] == 1
    assert confirmation["fingerprint"] == approval["fingerprint"] == stored["fingerprint"]
    assert approval["status"] == "approved" and approval["actor_id"] == confirmation["actor_id"]
    (order,) = rows("SELECT revision FROM orders")
    assert order["revision"] == stored["revision"]
    history = workflow.get_proposal(buyer, p["proposal_id"])["history"]
    confirmed = [e for e in history if e["event"] == "customer_confirmed"]
    assert [e["detail"]["revision"] for e in confirmed] == [1]
    assert confirmed[0]["detail"]["fingerprint"] == stored["fingerprint"]


def test_accepting_a_substitute_does_not_carry_to_a_repriced_revision(
    service, connector, buyer, actor, mission, monkeypatch
):
    p = service.prepare_order(actor, mission)
    body = body_for(p)
    original = service.commit_order

    def supplier_down(*args):
        raise Problem("SUPPLIER_UNAVAILABLE", "down", 503)

    monkeypatch.setattr(service, "commit_order", supplier_down)
    with pytest.raises(Problem):
        conversations.confirm(buyer, p["proposal_id"], body, service)
    monkeypatch.setattr(service, "commit_order", original)
    connector.price_multiplier = Decimal("1.1")  # the terms change before the order is placed
    revised = original(actor, body)
    assert revised["status"] == "revised" and revised["revision"] == 2
    assert [x["substitutes_for"] for x in revised["request"]["lines"]] == [None, "464306"]
    assert [r["revision"] for r in rows("SELECT revision FROM customer_confirmations")] == [1]
    with pytest.raises(Problem) as error:
        original(actor, body_for(p, revision=2))
    assert error.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"
    assert rows("SELECT id FROM orders") == []
