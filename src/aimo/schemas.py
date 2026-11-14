from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, model_validator

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
    recipe_plan_id: UUID | None = None
    recipe_plan_revision: int | None = Field(default=None, ge=1)
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


class PrepareRequest(PurchaseRequest):
    idempotency_key: str = Field(
        min_length=8,
        max_length=120,
        description="Stable key for retries of this preparation, scoped to buyer and agent. Use a new key for a new purchase or fresh proposal after expiry.",
    )


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
    type: Literal[
        "commit",
        "wait",
        "revise_request",
        "request_fresh_proposal",
        "stop",
        "complete",
        "view_current_proposal",
    ]
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
    current_revision: int
    committed_revision: int | None
    current_proposal_url: str
    policy_version: int
    policy_outcome: Literal["ready_to_commit", "approval_required", "denied", "needs_resolution"]
    recipe_basis: Literal["saved_recipe", "free_form"] = "free_form"
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
    approved_product_ids: list[str] | None = Field(
        default=None,
        description="Buyer-configured product scope. Outside products count as substitutions even without an agent flag. Missing scope blocks regulated substitutions until privileged setup supplies it.",
    )


class AgentAuthority(Model):
    currency: Literal["EUR"]
    autonomous_limit: Money


class ApproverAuthority(Model):
    currency: Literal["EUR"]
    max_gross: Money
    exceptions: list[Literal["spend", "substitution", "overbuy"]]


class Measure(Model):
    value: str | None
    status: Literal["known", "unknown", "conflicting"]
    basis: list[str]
    name_hint: str | None = None


class Provenance(Model):
    source: str
    product_id: str


class ProductSummary(Model):
    id: str
    name: str
    names: dict[str, str]
    sales_unit: str | None
    base_unit: str | None
    units: dict[str, str]
    order_step: str
    measures: dict[str, Measure]
    claims: list[str]
    allergens: dict[str, Literal["CONTAINS", "MAY_CONTAIN"]]
    free_from: list[str]
    provenance: Provenance


class SearchCandidate(ProductSummary):
    score: float
    match_is_suitability_proof: Literal[False]


class SearchResponse(Model):
    products: list[SearchCandidate]
    generation: str
    model: str
    strategy: Literal["keyword", "semantic", "hybrid"]
    rerank_status: Literal["disabled", "applied", "unavailable"] = "disabled"
    note: str


class ProductResponse(ProductSummary):
    gtin: str | None
    variable_weight: bool
    allergen_conflicts: list[str]
    conflicts: list[str]
    deposits: list[JsonValue] = Field(description="Original supplier deposit declarations.")
    substitutions: list[JsonValue] = Field(
        description="Original supplier substitution declarations."
    )
    category: JsonValue
    country_of_origin: JsonValue
    deleted: bool
    packaging: list[JsonValue] = Field(description="Original supplier packaging evidence.")
    brand: str | None = None
    vendor_name: str | None = None
    descriptions: list[JsonValue] = Field(default_factory=list)


class PolicyResponse(Model):
    buyer_id: str
    agent_id: str
    policy_version: int
    rules: PolicyRules
    spend_basis: str
    editable: Literal[False]


class CommercialSource(Model):
    price: dict[str, JsonValue] | None
    availability: dict[str, JsonValue] | None


class CommercialEvidence(Model):
    product_id: str
    currency: str | None
    net: str | None
    gross: str | None
    tax_rate: str | None
    available_sales_quantity: str | None
    expires_at: datetime
    reasons: list[Reason]
    mode: str
    observed_at: datetime
    source: CommercialSource


class LookupResponse(Model):
    mode: str
    products: dict[str, CommercialEvidence]


class OrderResponse(Model):
    order_id: str
    proposal_id: str
    revision: int
    policy_version: int
    status: Literal["accepted_mock"]
    policy_outcome: Literal["ready_to_commit", "approval_required"]
    approval_status: Literal["not_required", "approved"]
    order_status: Literal["accepted_mock"]
    reasons: list[Reason]
    expires_at: datetime
    next_action: NextAction
    label: str
    upstream_order_placed: Literal[False]
    inventory_reserved: Literal[False]
    buyer_id: str
    gross_total: str
    currency: str
    evidence_mode: str
    accepted_at: datetime
    explanation: str


class RevisedProposalResponse(ProposalResponse):
    status: Literal["revised"]


class CommitResponse(
    RootModel[Annotated[OrderResponse | RevisedProposalResponse, Field(discriminator="status")]]
):
    # Preserve the flat, status-discriminated browser confirmation result.
    model_config = ConfigDict(json_schema_extra={"type": "object"})
