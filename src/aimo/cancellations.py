"""Cancelled order requests (CNF-035, Q-77).

Orders are immutable (CNF-020), so "cancelled" is never an update of an order. It is an
append-only record next to the order REQUEST (the proposal): `order_request_cancellations`,
one row per proposal, written once. A placed order can never be cancelled; the database trigger
and `cancel_request` both refuse it. The table itself belongs to the scheduler migration.
"""

from aimo.db import Problem, connection, js
from aimo.purchases import context

REASONS = ("run_disrupted", "run_retry", "customer_revised", "customer_cancelled")


def cancel_request(c, proposal_id, buyer_id, reason, run_id=None, by=None):
    """Record a cancellation inside the caller's transaction; True if written, False if the
    request was already cancelled (the first record stands). A placed order is refused."""
    if reason not in REASONS:
        raise ValueError(f"Unknown cancellation reason {reason!r}.")
    if not by:
        raise ValueError("A cancellation names the identity that made it.")
    p = c.execute(
        "SELECT order_id FROM proposals WHERE id=%s AND buyer_id=%s FOR UPDATE",
        (proposal_id, buyer_id),
    ).fetchone()
    if not p:
        raise Problem("NOT_FOUND", "Purchase not found.", 404)
    if p["order_id"]:
        raise Problem("ORDER_ALREADY_PLACED", "A placed order cannot be cancelled.", 409)
    written = c.execute(
        """INSERT INTO order_request_cancellations(proposal_id,buyer_id,reason,run_id,cancelled_by)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT (proposal_id) DO NOTHING RETURNING proposal_id""",
        (proposal_id, buyer_id, reason, run_id, by),
    ).fetchone()
    return written is not None


def is_cancelled(c, proposal_id):
    return (
        c.execute(
            "SELECT 1 FROM order_request_cancellations WHERE proposal_id=%s", (proposal_id,)
        ).fetchone()
        is not None
    )


def ensure_not_cancelled(c, proposal_id):
    """A cancelled request never commits or gets confirmed."""
    row = c.execute(
        "SELECT reason FROM order_request_cancellations WHERE proposal_id=%s", (proposal_id,)
    ).fetchone()
    if row and row["reason"] == "customer_revised":
        # The cart changed after this basket was shown: the customer is sent to the newer one.
        raise Problem(
            "REQUEST_REVISED",
            "The basket was revised. Review the new basket and confirm that one.",
            409,
        )
    if row:
        raise Problem("REQUEST_CANCELLED", "This order request was cancelled.", 409)


def cancel_my_request(identity, proposal_id):
    """The customer cancels one of their own pending requests (idempotent)."""
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only a buyer session can cancel an order request.", 403)
    with connection() as c:
        context(c, identity, lock=True)  # same lock order as commit: buyer, then the proposal
        # cancel_request locks the proposal row and answers NOT_FOUND for another buyer's.
        written = cancel_request(
            c, proposal_id, identity["buyer_id"], "customer_cancelled", None, identity["id"]
        )
        if written:
            c.execute(
                "INSERT INTO audit_events(proposal_id,actor_id,event,detail) VALUES(%s,%s,%s,%s)",
                (proposal_id, identity["id"], "request_cancelled", js({})),
            )
        row = c.execute(
            "SELECT * FROM order_request_cancellations WHERE proposal_id=%s", (proposal_id,)
        ).fetchone()
    return {
        "proposal_id": str(row["proposal_id"]),
        "reason": row["reason"],
        "cancelled_by": row["cancelled_by"],
        "cancelled_at": row["created_at"],
    }
