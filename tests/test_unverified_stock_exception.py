"""Q-134 (b): UNVERIFIED_STOCK is an approvable EXCEPTION, not a blocker.

The live supplier mostly answers with lines that are not 'Stock' or carry placeholder amounts, so nearly
every basket was `needs_resolution`. Now the customer may approve it: the basket is `approval_required`
with the exception listed, it can be committed only after the customer's own exact-revision
confirmation (never by the agent), and the order record carries the reason. QUANTITY_UNRESOLVED,
TOTAL_UNRESOLVED and CUTOFF_PASSED stay blockers; so do all other checks. Orders are mocks.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo import conversations, policy_scope
from aimo.approval_policy import evaluate_purchase
from aimo.db import Problem, connection, js
from aimo.scheduler import helsinki_today
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest

APPROVER = {"currency": "EUR", "max_gross": "5000", "exceptions": ["substitution", "overbuy"]}
LIMITED = {"currency": "EUR", "max_gross": "1.00", "exceptions": []}
STOCK = dict(
    code="UNVERIFIED_STOCK",
    message="Supplier or placeholder stock does not confirm fulfillment.",
    product_id="P",
    severity="exception",
)


@pytest.fixture(autouse=True)
def wide_policy():
    """Scope and overbuy are not under test here: use the Q-134 (a) policy for the fixture catalogue."""
    with connection() as c:
        row = c.execute(
            "SELECT p.rules FROM policies p JOIN buyers b ON b.id=p.buyer_id AND p.version=b.current_policy"
            " WHERE b.id='demo-hotel'"
        ).fetchone()
        wide = policy_scope.widened_rules(row["rules"], policy_scope.catalog_product_ids(c))
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)", (js(wide),)
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")


def prepare(service, agent, lines):
    body = {
        "request_id": "Q-134 stock",
        "idempotency_key": str(uuid4()),
        "destination": "hotel-helsinki",
        "delivery_date": str(helsinki_today() + timedelta(days=2)),
        "lines": lines,
    }
    identity = agent | {"_turn_id": str(uuid4())}
    return service.prepare_order(identity, PrepareRequest.model_validate(body))


def codes(proposal):
    return {r["code"] for r in proposal["reasons"]}


@pytest.fixture
def unverified(connector):
    connector.stock["464398"] = "999999"  # the supplier's placeholder: stock is not confirmed


LINE = [{"product_id": "464398", "amount": "10", "unit": "L"}]


# --- the outcome ----------------------------------------------------------------------------------


def test_a_basket_whose_only_reason_is_unverified_stock_needs_the_customers_approval(
    service, agent, unverified
):
    p = prepare(service, agent, LINE)
    assert codes(p) == {"UNVERIFIED_STOCK"}
    assert p["policy_outcome"] == "approval_required"
    assert p["reason_classes"] == {"UNVERIFIED_STOCK": "exception"}
    assert p["approval_status"] == "pending" and p["approval_id"]
    with connection() as c:
        stored = c.execute(
            "SELECT required_exceptions FROM proposal_revisions WHERE proposal_id=%s",
            (p["proposal_id"],),
        ).fetchone()
    assert "unverified_stock" in stored["required_exceptions"]


def test_it_is_confirmable_only_after_the_customers_own_confirmation(
    service, agent, buyer, unverified
):
    p = prepare(service, agent, LINE)
    commit = CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )
    with pytest.raises(Problem) as error:  # before: the agent cannot commit on its own
        service.commit_order(agent, commit)
    assert error.value.code in {"CUSTOMER_CONFIRMATION_REQUIRED", "APPROVAL_REQUIRED"}
    receipt = conversations.confirm(buyer, p["proposal_id"], commit, service)  # the customer
    assert receipt["status"] == "accepted_mock" and receipt["label"].startswith("Accepted by demo")
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 1


def test_the_agent_cannot_approve_or_confirm_it(service, agent, unverified):
    p = prepare(service, agent, LINE)
    with pytest.raises(Problem) as error:
        workflow.record_human_decision(
            agent, p["approval_id"], DecisionRequest(revision=p["revision"], decision="approve")
        )
    assert error.value.code == "FORBIDDEN"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


def test_the_order_record_carries_the_exception(service, agent, buyer, unverified):
    p = prepare(service, agent, LINE)
    commit = CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )
    receipt = conversations.confirm(buyer, p["proposal_id"], commit, service)
    assert receipt["policy_outcome"] == "approval_required"
    assert receipt["approval_status"] == "approved"
    assert [r["code"] for r in receipt["reasons"]] == ["UNVERIFIED_STOCK"]
    assert receipt["approved_exceptions"] == ["unverified_stock"]
    with connection() as c:
        stored = c.execute("SELECT receipt FROM orders").fetchone()["receipt"]
    assert stored["approved_exceptions"] == ["unverified_stock"]
    assert any(r["code"] == "UNVERIFIED_STOCK" for r in stored["reasons"])


def test_an_approver_with_a_small_limit_still_cannot_approve_a_larger_amount(
    service, agent, unverified
):
    """The exception needs no listed authority, but the amount limit still applies."""
    with connection() as c:
        c.execute("UPDATE identities SET authority=%s WHERE id='buyer'", (js(LIMITED),))
    p = prepare(service, agent, LINE)
    assert p["policy_outcome"] == "needs_resolution" and "NO_ELIGIBLE_APPROVER" in codes(p)


# --- what stays a blocker --------------------------------------------------------------------------


def run(*reasons):
    snapshot = {
        "reasons": list(reasons),
        "currency": "EUR",
        "gross_total": "10.00",
        "lines": [{"quantity": {"excess": "0"}}],
    }
    rules = {
        "currency": "EUR",
        "destinations": ["hotel"],
        "substitution": "requires_approval",
        "overbuy": "allowed",
        "whole_sales_units": True,
        "approved_product_ids": ["P"],
    }
    request = {"destination": "hotel", "lines": [{"product_id": "P"}]}
    return evaluate_purchase(request, snapshot, rules, [APPROVER])


def blocker(code, severity="unresolved"):
    return dict(code=code, message="m", product_id="P", severity=severity)


def test_alone_it_is_an_exception_with_the_exception_listed():
    result = run(STOCK)
    assert result["policy_outcome"] == "approval_required"
    assert result["required_exceptions"] == ["unverified_stock"]


@pytest.mark.parametrize("code", ["QUANTITY_UNRESOLVED", "TOTAL_UNRESOLVED", "CUTOFF_PASSED"])
def test_with_a_real_blocker_the_basket_is_still_blocked(code):
    assert run(STOCK, blocker(code))["policy_outcome"] == "needs_resolution"


@pytest.mark.parametrize(
    "code", ["SALES_BLOCK", "DELIVERY_UNRESOLVED", "MISSING_PRICE", "PRICE_OUTSIDE_VALIDITY"]
)
def test_every_other_supplier_check_still_blocks(code):
    assert run(STOCK, blocker(code))["policy_outcome"] == "needs_resolution"


def test_a_denied_reason_still_wins():
    assert run(STOCK, blocker("PRODUCT_DELETED", "denied"))["policy_outcome"] == "denied"


def test_a_scheduled_standing_order_is_never_run_on_unverified_stock():
    from aimo import scheduler

    auth = {
        "currency": "EUR",
        "line_rules": {},
        "agreed_lines": [],
        "request": {"destination": "hotel"},
        "price_ceiling_gross": "100",
        "agreed_gross_total": "10",
    }
    snapshot = {"reasons": [STOCK], "currency": "EUR", "gross_total": "10.00", "lines": []}
    verdict = scheduler.compare(auth, {"destination": "hotel"}, snapshot, "approval_required")
    assert not verdict["ok"] and "POLICY_NOT_READY" in verdict["codes"]
