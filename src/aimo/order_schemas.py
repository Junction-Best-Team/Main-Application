"""Response models of the orders list and of cancelling an order request (CNF-034, CNF-035)."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from aimo.schemas import Model


class OrderListItem(Model):
    status: Literal["scheduled", "pending", "placed", "cancelled"]
    title: str | None = None
    scheduled_for: str | None = None  # ISO date of the next run, for `scheduled` only
    proposal_id: str | None = None
    order_id: str | None = None  # the mock order, for `placed` only
    schedule_id: str | None = (
        None  # the standing order: the row itself, or the one whose run made it
    )
    schedule_title: str | None = None  # the standing order's label, for "from standing order ..."
    paused: bool = False  # a paused standing order (`scheduled` rows only)
    gross_total: str | None = None
    currency: str | None = None
    line_count: int
    line_names: list[str] = Field(default_factory=list, max_length=5)  # biggest line total first
    cancel_reason: (
        Literal["run_disrupted", "run_retry", "customer_revised", "customer_cancelled"] | None
    ) = None
    placed_at: datetime | None = None  # the mock order's time, `placed` rows only
    updated_at: datetime


class OrdersResponse(Model):
    items: list[OrderListItem]
    next_offset: int | None = None
    total: int  # every row matching the status filter, not just this page


class CancellationResponse(Model):
    proposal_id: str
    reason: Literal["run_disrupted", "run_retry", "customer_revised", "customer_cancelled"]
    cancelled_by: str
    cancelled_at: datetime
