"""Authenticated buyer policy settings; no agent-facing mutation tool."""

from typing import Annotated

from psycopg.errors import RaiseException
from pydantic import Field, field_validator

from aimo.db import Problem, connection, js
from aimo.purchases import context
from aimo.schemas import ApproverAuthority, Model, PolicyRules


class EditablePolicy(PolicyRules):
    destinations: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        min_length=1, max_length=50
    )
    approved_product_ids: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]] = Field(
        max_length=1000
    )

    @field_validator("destinations", "approved_product_ids", mode="before")
    @classmethod
    def normalize(cls, value):
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return sorted(set(v.strip() for v in value))
        return value


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


def manager(c, identity):
    return (
        c.execute(
            "SELECT 1 FROM policy_managers WHERE buyer_id=%s AND identity_id=%s",
            (identity["buyer_id"], identity["id"]),
        ).fetchone()
        is not None
    )


def render(c, identity):
    buyer, policy, actor, _ = context(c, identity)
    if actor["role"] != "approver":
        raise Problem("POLICY_FORBIDDEN", "Only signed-in buyers can view policy settings.", 403)
    history = c.execute(
        "SELECT version,actor_id,created_at FROM policy_changes WHERE buyer_id=%s ORDER BY version DESC LIMIT 20",
        (buyer["id"],),
    ).fetchall()
    return {
        "buyer_id": buyer["id"],
        "policy_version": policy["version"],
        "rules": PolicyRules.model_validate(policy["rules"]),
        "can_edit": manager(c, identity),
        "approval_authority": ApproverAuthority.model_validate(actor["authority"]),
        "history": [dict(row, created_at=row["created_at"].isoformat()) for row in history],
    }


def get(identity):
    with connection() as c:
        return render(c, identity)


def update(identity, request: PolicyUpdate):
    with connection() as c:
        _, policy, actor, _ = context(c, identity, lock=True)
        if actor["role"] != "approver" or not manager(c, identity):
            raise Problem(
                "POLICY_FORBIDDEN", "Only a policy manager can change purchasing rules.", 403
            )
        if request.expected_version != policy["version"]:
            raise Problem(
                "POLICY_CONFLICT", "Settings changed since you opened them. Reload before saving."
            )
        ids = request.rules.approved_product_ids
        found = c.execute(
            "SELECT id FROM products p JOIN active_catalog a ON a.generation=p.generation WHERE id=ANY(%s)",
            (ids,),
        ).fetchall()
        if set(ids) - {row["id"] for row in found}:
            raise Problem("UNKNOWN_PRODUCT", "Use product IDs from the current catalog.", 422)
        try:
            c.execute(
                "SELECT save_buyer_policy(%s,%s,%s)",
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
                    "POLICY_FORBIDDEN", "Policy management permission was revoked.", 403
                ) from None
            raise
        return render(c, identity)
