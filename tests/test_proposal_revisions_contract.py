"""Contract tests for proposal revisions and accepted substitutions (person 3, WS-D).

JNP3-PRP-003 (Approved): a supplier price or availability change gives a new revision of the
same proposal; a customer quantity change gives a new proposal. JNP3-PRP-007 (Draft): a
substitution the customer accepts is recorded against the proposal revision it applies to.
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


# --- JNP3-PRP-007 (Draft): a substitution the customer accepts is recorded against its revision ---


def test_existing_surface_ties_confirmation_and_substitution_exception_to_one_revision(
    service, buyer, actor, mission
):
    """What exists today: the substitution line and exception are in the revision, and the
    customer's confirmation and the approval are bound to that revision and fingerprint."""
    p = service.prepare_order(actor, mission)
    (stored,) = rows("SELECT required_exceptions FROM proposal_revisions")
    assert "substitution" in stored["required_exceptions"]
    assert [x["substitutes_for"] for x in p["request"]["lines"]] == [None, "464306"]
    conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    (revision,) = rows("SELECT fingerprint FROM proposal_revisions")
    (confirmation,) = rows("SELECT revision,fingerprint FROM customer_confirmations")
    assert (confirmation["revision"], confirmation["fingerprint"]) == (1, revision["fingerprint"])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "JNP3-PRP-007 not met: confirming records one whole-revision customer_confirmed audit "
        "event (detail has only revision and fingerprint); nothing names the accepted "
        "substitution (464398 for 464306) as such. Where it should live is undecided."
    ),
)
def test_accepting_a_substitution_is_recorded_as_such_against_its_revision(
    service, buyer, actor, mission
):
    p = service.prepare_order(actor, mission)
    conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    history = workflow.get_proposal(buyer, p["proposal_id"])["history"]
    accepted = [
        e for e in history if e["event"] == "customer_confirmed" and "464398" in str(e["detail"])
    ]
    assert accepted, "no audit event names the accepted substitute product"
    assert accepted[0]["detail"]["revision"] == 1
