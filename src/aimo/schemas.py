from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Amount = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=4)]
Money = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=4)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirements(Model):
    lactose_free: bool = False
    milk_free: bool = False


class SearchRequest(Model):
    query: str = Field(min_length=1, max_length=250)
    requirements: Requirements = Field(default_factory=Requirements)
    limit: int = Field(default=5, ge=1, le=20)


class LookupRequest(Model):
    product_ids: list[str] = Field(min_length=1, max_length=50)
    delivery_date: date


class LineRequest(Model):
    product_id: str = Field(min_length=1, max_length=40)
    amount: Amount
    unit: str = Field(
        min_length=1,
        max_length=12,
        description="Explicit catalog unit code, L or KG; boxes is ambiguous.",
    )
    substitutes_for: str | None = Field(default=None, max_length=40)


class PurchaseRequest(Model):
    request_id: str = Field(min_length=1, max_length=100)
    lines: list[LineRequest] = Field(min_length=1, max_length=30)
    destination: str = Field(min_length=1, max_length=120)
    delivery_date: date
    requirements: Requirements = Field(default_factory=Requirements)
    budget_gross: Money | None = None
    allow_substitution: bool = True
    allow_overbuy: bool = True

    @model_validator(mode="after")
    def unique_lines(self):
        ids = [line.product_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Combine quantities for duplicate product IDs before preparing")
        return self


class CommitRequest(Model):
    proposal_id: UUID
    revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class DecisionRequest(Model):
    revision: int = Field(ge=1)
    decision: Literal["approve", "reject"]


class LoginRequest(Model):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class Reason(Model):
    code: str
    message: str
    product_id: str | None = None
    severity: Literal["denied", "unresolved", "exception"]


class NextAction(Model):
    type: Literal["commit", "wait", "revise_request", "request_fresh_proposal", "stop", "complete"]
    tool: str | None = None
    poll_after_seconds: int | None = None


class QuantityCalculation(Model):
    requested_amount: str
    requested_unit: str
    sales_unit: str
    sales_quantity: str | None
    proposed_amount: str | None
    excess: str | None
    status: str
    basis: list[str]
    source_step: str
    effective_step: str | None = None


class SnapshotLine(Model):
    product_id: str
    name: str
    quantity: QuantityCalculation
    substitutes_for: str | None
    net: str | None
    gross: str | None
    tax: str | None
    deposits_gross: str | None
    deposit_lines: list[dict]
    product_evidence: dict
    commercial_evidence: dict


class PurchaseSnapshot(Model):
    lines: list[SnapshotLine]
    currency: str | None
    net_total: str | None
    gross_total: str | None
    tax_total: str | None
    deposits_gross: str | None
    charges_gross: str
    charges_basis: str
    mode: str
    observed_at: str
    reasons: list[Reason]


class ProposalResponse(Model):
    proposal_id: str
    revision: int
    policy_version: int
    policy_outcome: Literal["ready_to_commit", "approval_required", "denied", "needs_resolution"]
    approval_status: str
    order_status: str
    reasons: list[Reason]
    expires_at: datetime
    next_action: NextAction
    approval_id: str | None = None
    approval_url: str | None = None
    order_id: str | None = None
    buyer_id: str
    agent_id: str
    request: PurchaseRequest
    snapshot: PurchaseSnapshot
    history: list[dict] = Field(default_factory=list)
    can_decide: bool = False


class InboxResponse(Model):
    items: list[ProposalResponse]
    next_offset: int | None = None


class SessionResponse(Model):
    username: str
    buyer_id: str
    csrf_token: str


class PolicyRules(Model):
    currency: Literal["EUR"]
    autonomous_limit: Money
    destinations: list[str] = Field(min_length=1)
    substitution: Literal["allowed", "requires_approval", "forbidden"]
    overbuy: Literal["allowed", "requires_approval", "forbidden"]
    whole_sales_units: bool


class AgentAuthority(Model):
    currency: Literal["EUR"]
    autonomous_limit: Money


class ApproverAuthority(Model):
    currency: Literal["EUR"]
    max_gross: Money
    exceptions: list[Literal["spend", "substitution", "overbuy"]]
