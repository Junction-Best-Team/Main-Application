"""Request and response models of the scheduled (standing) orders, WS-E.

Every order the scheduler places is a MOCK order ("Accepted by demo order service"). Dates are
plain Helsinki calendar dates (runs execute from SCHEDULER_RUN_AFTER_HOUR, 06:00 Helsinki, on
the scheduled date); timestamps are ISO datetimes with an offset. Recurrence examples:

  weekly on Friday         {"kind": "weekdays", "weekdays": [4], "every_weeks": 1}
  Tuesday and Friday       {"kind": "weekdays", "weekdays": [1, 4], "every_weeks": 1}
  every other Friday       {"kind": "weekdays", "weekdays": [4], "every_weeks": 2}
  every 4 days (rolling)   {"kind": "days", "interval": 4}
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from aimo.schemas import Model, Money

MAX_SUBSTITUTES_PER_LINE = 5

Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=6, decimal_places=2)]
ScheduleStatus = Literal["active", "paused", "stopped", "cancelled", "expired", "superseded"]
RunStatus = Literal["due", "prepared", "committed", "disrupted", "skipped"]
LineStatus = Literal[
    "available_same_price",
    "price_within_range",
    "substituted",
    "price_outside_range",
    "unavailable",
    "withdrawn",
    "blocked_by_policy",
]


class Recurrence(Model):
    kind: Literal["days", "weekdays"]
    interval: int | None = Field(default=None, ge=1, le=365, description="kind=days: every N days")
    weekdays: list[int] | None = Field(
        default=None, description="kind=weekdays: 0 = Monday ... 6 = Sunday"
    )
    every_weeks: int = Field(default=1, ge=1, le=52, description="kind=weekdays: every N weeks")


class LineRule(Model):
    """Per ingredient (CNF-036, POL-012): the customer's accepted substitutes, chosen from the
    candidates the product page offers, and the price range around the agreed unit price."""

    accepted_substitutes: list[str] = Field(
        default_factory=list, max_length=MAX_SUBSTITUTES_PER_LINE
    )
    price_range_pct: Percent = Decimal("0")


class SchedulePreviewRequest(Model):
    order_id: UUID
    recurrence: Recurrence
    first_run_date: date
    line_rules: dict[str, LineRule] = Field(default_factory=dict, description="Key: product_id")


class ScheduleCreateRequest(SchedulePreviewRequest):
    price_ceiling_gross: Money
    agreed_terms_fingerprint: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)


class ScheduleEditPreviewRequest(Model):
    """Preview the terms of an existing schedule with optional changes (the edit page)."""

    recurrence: Recurrence | None = None
    first_run_date: date | None = None
    line_rules: dict[str, LineRule] | None = None
    source_order_id: UUID | None = None


class ScheduleReplaceRequest(ScheduleEditPreviewRequest):
    """Edit or restart: a new authorization that supersedes the old one."""

    price_ceiling_gross: Money | None = None
    agreed_terms_fingerprint: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)


class SubstituteCandidate(Model):
    product_id: str
    name: str
    unit_gross: str | None = None
    sales_unit: str | None = None


class ScheduleLine(Model):
    product_id: str
    name: str
    amount: str
    unit: str
    sales_quantity: str | None
    sales_unit: str | None
    unit_net: str | None
    unit_gross: str | None
    tax_rate: str | None
    line_gross: str | None
    accepted_substitutes: list[SubstituteCandidate] = Field(default_factory=list)
    price_range_pct: str = "0"


class ScheduleTerms(Model):
    """What the customer is asked to agree to; `terms_fingerprint` goes back in create/replace."""

    source_order_id: str
    title: str
    lines: list[ScheduleLine]
    currency: str | None
    gross_total: str | None
    policy_outcome: str
    terms_fingerprint: str
    delivery_offset_days: int
    recurrence: Recurrence
    first_run_date: date
    valid_until: date
    next_dates: list[date] = Field(description="The first scheduled dates, for the preview")
    blocking_reasons: list[dict] = Field(default_factory=list)


class RunLine(Model):
    product_id: str
    name: str | None = None
    status: LineStatus
    agreed_gross: str | None = None
    current_gross: str | None = None
    available_quantity: str | None = None
    substitute_product_id: str | None = None
    note: str | None = None


class RunReason(Model):
    codes: list[str] = Field(default_factory=list)
    lines: list[RunLine] = Field(default_factory=list)
    agreed_gross_total: str | None = None
    current_gross_total: str | None = None


class ScheduleRun(Model):
    id: str
    scheduled_date: date
    delivery_date: date
    status: RunStatus
    reason_code: str | None = None
    reason: RunReason | None = None
    substitutions: list[RunLine] = Field(default_factory=list)
    proposal_id: str | None = None
    order_id: str | None = None
    conversation_id: str | None = None
    updated_at: datetime


class ScheduleResponse(Model):
    id: str
    title: str
    status: ScheduleStatus
    stop_reason: str | None = None
    source_order_id: str
    supersedes_id: str | None = None
    replaced_by: str | None = Field(
        default=None, description="The schedule that replaced or restarted this one, if any"
    )
    recurrence: Recurrence
    first_run_date: date
    valid_until: date
    next_run_date: date | None = Field(description="Null once stopped, cancelled or expired")
    paused_at: datetime | None = None
    delivery_offset_days: int
    currency: str
    agreed_gross_total: str
    price_ceiling_gross: str
    lines: list[ScheduleLine]
    last_run: ScheduleRun | None = None
    conversation_id: str | None = Field(
        default=None, description="The chat of the latest disrupted run, if any"
    )
    created_at: datetime
    updated_at: datetime


class ScheduleDetail(ScheduleResponse):
    runs: list[ScheduleRun] = Field(description="Newest first, at most `runs_limit`")
    runs_next_offset: int | None = None


class ScheduleList(Model):
    items: list[ScheduleResponse]
    next_offset: int | None = None


class SubstituteCandidates(Model):
    product_id: str
    candidates: list[SubstituteCandidate]
