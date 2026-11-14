"""Authenticated buyer settings; no agent-facing mutation tool."""

from typing import Literal

from psycopg.errors import RaiseException
from pydantic import Field, field_serializer

from aimo.db import Problem, connection, js
from aimo.purchases import context
from aimo.schemas import ApproverAuthority, Model, OrderCap, PolicyRules


class EditablePolicy(Model):
    max_order_gross: OrderCap | None = None
    substitution: Literal["allowed", "requires_approval", "forbidden"]
    overbuy: Literal["allowed", "requires_approval", "forbidden"]
    whole_sales_units: bool

    @field_serializer("max_order_gross", when_used="json")
    def format_cap(self, value):
        return None if value is None else format(abs(value) if value == 0 else value, ".2f")


class PolicyUpdate(Model):
    expected_version: int = Field(ge=1)
    rules: EditablePolicy


class PolicyChange(Model):
    version: int
    actor_id: str
    created_at: str


class PolicySettings(Model):
    buyer_id: str
    policy_version: int
    rules: PolicyRules
    can_edit: bool
    approval_authority: ApproverAuthority
    history: list[PolicyChange]


def render(c, identity):
    buyer, policy, actor, _ = context(c, identity)
    if actor["role"] != "approver":
        raise Problem("POLICY_FORBIDDEN", "Only signed-in buyers can view purchasing rules.", 403)
    history = c.execute(
        "SELECT version,actor_id,created_at FROM policy_changes WHERE buyer_id=%s ORDER BY version DESC LIMIT 20",
        (buyer["id"],),
    ).fetchall()
    return {
        "buyer_id": buyer["id"],
        "policy_version": policy["version"],
        "rules": PolicyRules.model_validate(policy["rules"]),
        "can_edit": True,
        "approval_authority": ApproverAuthority.model_validate(actor["authority"]),
        "history": [dict(row, created_at=row["created_at"].isoformat()) for row in history],
    }


def get(identity):
    with connection() as c:
        return render(c, identity)


def update(identity, request: PolicyUpdate):
    with connection() as c:
        _, policy, actor, _ = context(c, identity, lock=True)
        if actor["role"] != "approver":
            raise Problem(
                "POLICY_FORBIDDEN", "Only signed-in buyers can change purchasing rules.", 403
            )
        if request.expected_version != policy["version"]:
            raise Problem(
                "POLICY_CONFLICT", "Settings changed since you opened them. Reload before saving."
            )
        try:
            c.execute(
                "SELECT save_buyer_settings(%s,%s,%s)",
                (actor["id"], request.expected_version, js(request.rules.model_dump(mode="json"))),
            )
        except RaiseException as exc:
            if exc.diag.message_primary == "POLICY_CONFLICT":
                raise Problem(
                    "POLICY_CONFLICT",
                    "Settings changed since you opened them. Reload before saving.",
                ) from None
            if exc.diag.message_primary == "POLICY_FORBIDDEN":
                raise Problem(
                    "POLICY_FORBIDDEN", "This buyer can no longer edit purchasing rules.", 403
                ) from None
            raise
        return render(c, identity)
