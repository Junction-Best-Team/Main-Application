"""Turn-scoped understanding of a customer's request, never purchase authority."""

from typing import Literal

from pydantic import Field

from aimo.db import Problem, connection, js, now
from aimo.schemas import Amount, Model, Requirements


class RequestBrief(Model):
    intent: Literal["explore", "build_list"]
    goal: str = Field(min_length=1, max_length=1000)
    starting_point: Literal["idea", "dish", "customer_recipe", "products"]
    portions: int | None = Field(default=None, ge=1, le=10000)
    recipe_reference: str | None = Field(default=None, max_length=2000)
    budget_gross: Amount | None = None
    requirements: Requirements = Field(default_factory=Requirements)
    missing_facts: list[str] = Field(default_factory=list, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=10)

    @property
    def can_build(self):
        return self.intent == "build_list" and not self.missing_facts


def load(c, cid, tid=None):
    row = c.execute(
        """SELECT request_brief FROM conversation_turns WHERE conversation_id=%s
        AND request_brief IS NOT NULL AND (%s::uuid IS NULL OR
        (created_at,id)<=(SELECT created_at,id FROM conversation_turns WHERE id=%s))
        ORDER BY created_at DESC,id DESC LIMIT 1""",
        (cid, tid, tid),
    ).fetchone()
    return RequestBrief.model_validate(row["request_brief"]) if row else None


def save(identity, brief):
    """Only the authenticated, still-running attempt can publish its understanding."""
    if not identity.get("_conversation_id"):
        return  # Direct internal tools have no customer conversation to mutate.
    with connection() as c:
        row = c.execute(
            """SELECT t.* FROM conversation_turns t JOIN conversations c
            ON c.id=t.conversation_id JOIN identities i ON i.id=t.requested_by
            WHERE t.id=%s AND t.conversation_id=%s AND c.buyer_id=%s
            AND i.buyer_id=c.buyer_id AND i.active AND i.role='approver' FOR UPDATE OF t""",
            (identity["_turn_id"], identity["_conversation_id"], identity["buyer_id"]),
        ).fetchone()
        if (
            not row
            or str(row["attempt"]) != str(identity.get("_attempt"))
            or row["state"] != "running"
            or row["lease_until"] <= now()
            or row["requested_by"] != identity.get("_requested_by")
            or row["submitted_by"] != identity.get("_requested_by")
        ):
            raise Problem("TURN_REPLACED", "This response was replaced; reload the conversation.")
        c.execute(
            "UPDATE conversation_turns SET request_brief=%s WHERE id=%s",
            (js(brief.model_dump(mode="json")), row["id"]),
        )


def apply(brief, request, plan=None):
    """A tool or background prepare may strengthen, but never loosen, the saved limits."""
    if not brief.can_build:
        raise Problem(
            "REQUEST_NOT_READY", "Help resolve the remaining meal or quantity choice first.", 422
        )
    if plan and brief.portions is not None and brief.portions != plan.portions:
        raise Problem(
            "REQUEST_QUANTITY_CHANGED",
            "Update the ingredient quantities for the requested portions first.",
            422,
        )
    a, b = brief.requirements, request.requirements
    origins = set(a.country_of_origin) & set(b.country_of_origin)
    if a.country_of_origin and b.country_of_origin and not origins:
        raise Problem("REQUEST_REQUIREMENTS_CONFLICT", "The origin requirements conflict.", 422)
    requirements = Requirements(
        lactose_free=a.lactose_free or b.lactose_free,
        milk_free=a.milk_free or b.milk_free,
        free_from=list(dict.fromkeys(a.free_from + b.free_from)),
        country_of_origin=sorted(origins)
        if origins
        else a.country_of_origin or b.country_of_origin,
        unsupported=list(dict.fromkeys(a.unsupported + b.unsupported)),
    )
    budgets = [n for n in (brief.budget_gross, request.budget_gross) if n is not None]
    return request.model_copy(
        update={
            "requirements": requirements,
            "budget_gross": min(budgets) if budgets else None,
        }
    )
