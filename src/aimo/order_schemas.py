"""Response models of the orders list and of cancelling an order request (CNF-034, CNF-035)."""

from datetime import datetime
from typing import Literal

from aimo.schemas import Model


class OrderListItem(Model):
    status: Literal["scheduled", "pending", "placed", "cancelled"]
    title: str | None = None
    scheduled_for: str | None = None  # ISO date of the next run, for `scheduled` only
    proposal_id: str | None = None
    order_id: str | None = None  # the mock order, for `placed` only
    schedule_id: str | None = None  # the standing order, for `scheduled` only
    gross_total: str | None = None
    currency: str | None = None
    line_count: int
    cancel_reason: (
        Literal["run_disrupted", "run_retry", "customer_revised", "customer_cancelled"] | None
    ) = None
    updated_at: datetime


class OrdersResponse(Model):
    items: list[OrderListItem]
    next_offset: int | None = None


class CancellationResponse(Model):
    proposal_id: str
    reason: Literal["run_disrupted", "run_retry", "customer_revised", "customer_cancelled"]
    cancelled_by: str
    cancelled_at: datetime
