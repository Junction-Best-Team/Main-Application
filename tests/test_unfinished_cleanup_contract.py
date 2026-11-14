"""CNF-021 (Approved): remove proposals and approvals that never became orders after a configured
period. Orders, their proposals and their audit history are never removed (CNF-017, CNF-020).

`test_..._are_removed...` runs `aimo.approval_workflow.purge_unfinished_proposals(older_than, *,
as_of=None)` (migration 018), which returns counts; design in
Assistant/projects/junction/evidence/ws-d/cnf-021-design.md. The guard test
`test_every_table_referencing_proposals_is_known_to_the_cleanup_design` passes today and fails if a
new table starts referencing proposals without the cleanup design covering it.

Fixture catalog and invented FixtureClient prices only; orders are mock acceptance.
"""

from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.db import Problem, connection, now
from aimo.schemas import CommitRequest, PrepareRequest

# Every table with a foreign key to proposals or proposal_revisions, and what cleanup must do.
CLEANUP_DESIGN = {
    "proposal_revisions": "delete (immutable trigger must allow it for unordered proposals)",
    "approvals": "delete (references proposal_revisions)",
    "audit_events": "delete (immutable trigger must allow it for unordered proposals)",
    "customer_confirmations": "delete (immutable trigger; references proposal_revisions)",
    "prepare_requests": "delete (retry keys of a removed proposal)",
    "recipe_plans": "set proposal_id NULL and locked false (the plan stays reusable)",
    "conversation_messages": "set proposal_id NULL (the chat text stays)",
    "meal_authorization_withdrawals": "delete (exists once migration 010 is applied)",
    "orders": "never touched: an ordered proposal is not unfinished",
}


def referencing_tables():
    with connection() as c:
        rows = c.execute(
            """SELECT DISTINCT cl.relname AS table_name
            FROM pg_constraint k JOIN pg_class cl ON cl.oid=k.conrelid
            WHERE k.contype='f' AND k.confrelid IN ('proposals'::regclass, 'proposal_revisions'::regclass)
            AND cl.relnamespace=current_schema()::regnamespace"""
        ).fetchall()
    return {r["table_name"] for r in rows}


def test_every_table_referencing_proposals_is_known_to_the_cleanup_design(
    service, buyer, request_data
):
    unknown = referencing_tables() - set(CLEANUP_DESIGN)
    assert not unknown, f"cleanup design does not cover {sorted(unknown)}"
    # Today nothing may delete history (row triggers need a row to fire on): the cleanup is
    # impossible without a reviewed change to the immutable triggers.
    service.prepare_order(auth.internal_agent(buyer), PrepareRequest.model_validate(request_data))
    for table in ("audit_events", "proposal_revisions"):
        with pytest.raises(psycopg.errors.RaiseException):
            with connection() as c:
                c.execute(f"DELETE FROM {table}")


def counts(proposal_id):
    """Rows that hang on one proposal, per table."""
    tables = (
        "proposal_revisions",
        "approvals",
        "audit_events",
        "customer_confirmations",
        "prepare_requests",
    )
    with connection() as c:
        result = {
            table: c.execute(
                f"SELECT count(*) AS n FROM {table} WHERE proposal_id=%s", (proposal_id,)
            ).fetchone()["n"]
            for table in tables
        }
        result["proposals"] = c.execute(
            "SELECT count(*) AS n FROM proposals WHERE id=%s", (proposal_id,)
        ).fetchone()["n"]
    return result


# CNF-021 (Approved): implemented by migration 018 and workflow.purge_unfinished_proposals.
def test_unfinished_proposals_and_approvals_are_removed_after_the_period_and_orders_are_kept(
    service, buyer, request_data, monkeypatch
):
    actor = auth.internal_agent(buyer)

    def prepared(amount):
        data = request_data | {
            "idempotency_key": str(uuid4()),
            "lines": [{"product_id": "464306", "amount": amount, "unit": "L"}],
        }
        return service.prepare_order(actor, PrepareRequest.model_validate(data))

    def body(p):
        return CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))

    ordered = prepared("10")
    receipt = conversations.confirm(buyer, ordered["proposal_id"], body(ordered), service)
    pending = prepared("11")  # an approval is pending, never decided
    confirmed_only = prepared("12")  # confirmed, but the supplier was down: no order
    original = service.commit_order

    def supplier_down(*args):
        raise Problem("SUPPLIER_UNAVAILABLE", "down", 503)

    monkeypatch.setattr(service, "commit_order", supplier_down)
    with pytest.raises(Problem):
        conversations.confirm(buyer, confirmed_only["proposal_id"], body(confirmed_only), service)
    monkeypatch.setattr(service, "commit_order", original)
    unfinished = [pending["proposal_id"], confirmed_only["proposal_id"]]
    ordered_before = counts(ordered["proposal_id"])

    period = timedelta(days=30)
    # Inside the period nothing is removed.
    result = workflow.purge_unfinished_proposals(period, as_of=now() + timedelta(days=10))
    assert result["proposals"] == 0 and all(counts(p)["proposals"] == 1 for p in unfinished)
    # After the period the unfinished proposals and every row that hangs on them are removed.
    result = workflow.purge_unfinished_proposals(period, as_of=now() + timedelta(days=31))
    assert result["proposals"] == 2
    for pid in unfinished:
        assert set(counts(pid).values()) == {0}
    # Q-57: one append-only record per removed proposal; none for the ordered one.
    with connection() as c:
        purged = c.execute("SELECT proposal_id FROM purged_proposals").fetchall()
    assert {str(r["proposal_id"]) for r in purged} == set(unfinished)
    # The order, its proposal, revisions, confirmation, approval and audit history stay intact.
    assert counts(ordered["proposal_id"]) == ordered_before
    assert service.get_order(actor, receipt["order_id"]) == receipt
    # Orders stay immutable afterwards (CNF-020).
    with pytest.raises(psycopg.errors.RaiseException):
        with connection() as c:
            c.execute("DELETE FROM orders")
