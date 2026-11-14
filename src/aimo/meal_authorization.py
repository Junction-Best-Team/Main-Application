"""Per-meal authorization (JNP3-POL-010).

A per-meal authorization is the customer's approval of one proposal revision: an approved
`approvals` row or a `customer_confirmations` row. The agent can never create either, so it can
never grant one. It expires with the proposal (`proposal_revisions.expires_at`) and it never
touches the standing `approved_product_ids` list. Withdrawal is a Service operation for the
buyer's authenticated customer (not an agent tool): it is terminal for the proposal, supersedes
any open approval and is recorded append-only in `meal_authorization_withdrawals`.
"""

from uuid import UUID

from pydantic import Field, model_validator

from aimo.db import Problem, connection, js, now
from aimo.purchases import context
from aimo.schemas import Model


class WithdrawMealAuthorization(Model):
    proposal_id: UUID | None = None
    plan_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def one_target(self):
        if (self.proposal_id is None) == (self.plan_id is None):
            raise ValueError("Name exactly one of proposal_id or recipe plan_id")
        return self


def withdrawal(c, proposal_id):
    return c.execute(
        "SELECT * FROM meal_authorization_withdrawals WHERE proposal_id=%s", (proposal_id,)
    ).fetchone()


def is_withdrawn(c, proposal_id):
    return withdrawal(c, proposal_id) is not None


def ensure_active(c, proposal_id):
    """Commit-time guard: a withdrawn proposal can never be committed."""
    if is_withdrawn(c, proposal_id):
        raise Problem(
            "AUTHORIZATION_WITHDRAWN",
            "The customer's authorization for this basket was withdrawn; prepare a fresh basket.",
        )


def current_revision(c, proposal):
    return c.execute(
        "SELECT * FROM proposal_revisions WHERE proposal_id=%s AND revision=%s",
        (proposal["id"], proposal["current_revision"]),
    ).fetchone()


def describe(c, proposal):
    """The authorization record for a proposal's current revision (derived, never stored)."""
    pid, revision = proposal["id"], current_revision(c, proposal)
    gone = withdrawal(c, pid)
    grant = c.execute(
        """SELECT actor_id,created_at AS at FROM customer_confirmations
        WHERE proposal_id=%s AND revision=%s ORDER BY created_at LIMIT 1""",
        (pid, revision["revision"]),
    ).fetchone() or c.execute(
        """SELECT actor_id,decided_at AS at FROM approvals WHERE proposal_id=%s AND revision=%s
        AND status IN ('approved','superseded') AND actor_id IS NOT NULL""",
        (pid, revision["revision"]),
    ).fetchone()
    if gone:
        status = "withdrawn"
    elif not grant:
        status = "not_granted"
    elif proposal["order_id"]:
        status = "used"
    elif revision["expires_at"] <= now():
        status = "expired"
    else:
        status = "active"
    plan_id = gone["plan_id"] if gone else None
    if plan_id is None:
        linked = c.execute("SELECT id FROM recipe_plans WHERE proposal_id=%s", (pid,)).fetchone()
        plan_id = linked["id"] if linked else None
    return {
        "proposal_id": str(pid),
        "plan_id": str(plan_id) if plan_id else None,
        "revision": revision["revision"],
        "product_ids": sorted({line["product_id"] for line in revision["request"]["lines"]}),
        "status": status,
        "granted_by": grant["actor_id"] if grant else None,
        "granted_at": grant["at"] if grant else None,
        "expires_at": revision["expires_at"],
        "withdrawn_at": gone["created_at"] if gone else None,
        "withdrawn_by": gone["withdrawn_by"] if gone else None,
        "reason": gone["reason"] if gone else None,
    }


def owned_proposal(c, buyer_id, proposal_id, lock=False):
    row = c.execute(
        "SELECT * FROM proposals WHERE id=%s AND buyer_id=%s" + (" FOR UPDATE" if lock else ""),
        (proposal_id, buyer_id),
    ).fetchone()
    if not row:
        raise Problem("NOT_FOUND", "Purchase not found.", 404)
    return row


def get(identity, proposal_id):
    with connection() as c:
        context(c, identity)
        return describe(c, owned_proposal(c, identity["buyer_id"], proposal_id))


def withdraw(identity, request: WithdrawMealAuthorization):
    with connection() as c:
        # Same lock order as every purchasing change: buyer first, then the proposal.
        _, _, actor, _ = context(c, identity, lock=True)
        if actor["role"] != "approver":
            raise Problem(
                "FORBIDDEN",
                "Only the buyer's signed-in customer can withdraw an authorization.",
                403,
            )
        plan_id, proposal_id = request.plan_id, request.proposal_id
        if plan_id is not None:
            plan = c.execute(
                "SELECT * FROM recipe_plans WHERE id=%s AND buyer_id=%s",
                (plan_id, identity["buyer_id"]),
            ).fetchone()
            if not plan:
                raise Problem("NOT_FOUND", "Recipe plan not found.", 404)
            proposal_id = plan["proposal_id"]
            if proposal_id is None:  # nothing was prepared from this plan, so nothing to withdraw
                return {
                    "proposal_id": None,
                    "plan_id": str(plan_id),
                    "revision": None,
                    "product_ids": [],
                    "status": "not_granted",
                    "granted_by": None,
                    "granted_at": None,
                    "expires_at": None,
                    "withdrawn_at": None,
                    "withdrawn_by": None,
                    "reason": None,
                }
        proposal = owned_proposal(c, identity["buyer_id"], proposal_id, lock=True)
        if withdrawal(c, proposal["id"]):
            return describe(c, proposal)
        if proposal["order_id"]:
            raise Problem(
                "ALREADY_COMMITTED", "This purchase already has an order; it cannot be withdrawn."
            )
        revision = current_revision(c, proposal)
        plan = plan_id or (
            c.execute("SELECT id FROM recipe_plans WHERE proposal_id=%s", (proposal["id"],))
            .fetchone()
            or {}
        ).get("id")
        c.execute(
            """INSERT INTO meal_authorization_withdrawals
            (proposal_id,buyer_id,plan_id,revision,withdrawn_by,reason) VALUES(%s,%s,%s,%s,%s,%s)""",
            (
                proposal["id"],
                identity["buyer_id"],
                plan,
                revision["revision"],
                actor["id"],
                request.reason,
            ),
        )
        c.execute(
            "UPDATE approvals SET status='superseded' WHERE proposal_id=%s "
            "AND status IN ('pending','approved')",
            (proposal["id"],),
        )
        c.execute(
            "INSERT INTO audit_events(proposal_id,actor_id,event,detail) VALUES(%s,%s,%s,%s)",
            (
                proposal["id"],
                actor["id"],
                "meal_authorization_withdrawn",
                js(
                    {
                        "revision": revision["revision"],
                        "reason": request.reason,
                        "plan_id": str(plan) if plan else None,
                        "product_ids": sorted(
                            {line["product_id"] for line in revision["request"]["lines"]}
                        ),
                    }
                ),
            ),
        )
        return describe(c, proposal)
