from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    field_validator,
    model_serializer,
    model_validator,
)

# MEA-013 (owner Q-67): a meal plan, a saved recipe and a purchase request hold at most 100
# ingredients/lines. The supplier's own per-request limit is 1000 product ids; the lookup keeps it
# (SUP-007 splits larger lookups into batches), so it is deliberately not tied to the 100.
MAX_BASKET_LINES = 100
MAX_LOOKUP_IDS = 1000
Amount = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=4)]
Money = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=4)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirements(Model):
    lactose_free: bool = False
    milk_free: bool = False
    free_from: list[Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9]{0,3}$")]] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Allergen codes (for example AM milk, AE, AW) the product must explicitly declare "
            "free from. A product with no declaration is excluded, not assumed safe."
        ),
    )
    country_of_origin: list[Annotated[str, Field(pattern=r"^[A-Za-z]{2}$")]] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Two-letter origin codes (for example fi, se); the product must match one. "
            "A product with no recorded origin is excluded."
        ),
    )
    unsupported: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list,
        max_length=10,
        description="Customer requirements the catalog cannot verify (for example gluten-free). "
        "Each entry blocks readiness: the basket needs the customer's decision (POL-009).",
    )

    @field_validator("free_from")
    @classmethod
    def _upper_codes(cls, codes):
        return list(dict.fromkeys(code.upper() for code in codes))

    @field_validator("country_of_origin")
    @classmethod
    def _lower_codes(cls, codes):
        return list(dict.fromkeys(code.lower() for code in codes))

    @model_serializer(mode="wrap")
    def _omit_unset_filters(self, handler):
        # Keeps stored request fingerprints from before these fields existed unchanged.
        data = handler(self)
        for name in ("free_from", "country_of_origin", "unsupported"):
            if not data.get(name):
                data.pop(name, None)
        return data


class SearchRequest(Model):
    query: str = Field(min_length=1, max_length=250)
    requirements: Requirements = Field(default_factory=Requirements)
    limit: int = Field(default=5, ge=1, le=20)


class LookupRequest(Model):
    product_ids: list[str] = Field(min_length=1, max_length=MAX_LOOKUP_IDS)
    # Engineering guard, not an owner rule: 0001-01-01 is valid ISO but broke the supplier call path.
    delivery_date: date = Field(ge=date(2000, 1, 1), le=date(2100, 12, 31))


class Contribution(Model):
    """One ingredient's required quantity inside a basket line (BAS-002, MEA-005)."""

    ingredient: str = Field(min_length=1, max_length=240)
    ingredient_id: str | None = Field(default=None, max_length=120)
    amount: Amount
    unit: str = Field(min_length=1, max_length=12)


class LineRequest(Model):
    product_id: str = Field(min_length=1, max_length=40)
    amount: Amount
    unit: str = Field(
        min_length=1,
        max_length=12,
        description="Explicit catalog unit code, L or KG; boxes is ambiguous.",
    )
    substitutes_for: str | None = Field(default=None, max_length=40)
    contributions: list[Contribution] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_BASKET_LINES,
        description="Free-form baskets: the ingredients this line serves; amounts add up to it.",
    )

    @model_validator(mode="after")
    def contributions_add_up(self):
        parts = self.contributions or []
        if parts and all(c.unit == self.unit for c in parts):
            if sum(c.amount for c in parts) != self.amount:
                raise ValueError("Contributions must add up to the line amount")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_contributions(self, handler):
        # Keeps the dump (stored request, retry hash, fingerprints) of earlier lines unchanged.
        data = handler(self)
        if data.get("contributions") is None:
            data.pop("contributions", None)
        return data


class PurchaseRequest(Model):
    recipe_plan_id: UUID | None = None
    recipe_plan_revision: int | None = Field(default=None, ge=1)
    request_id: str = Field(min_length=1, max_length=100)
    lines: list[LineRequest] = Field(min_length=1, max_length=MAX_BASKET_LINES)
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
        if self.recipe_plan_id and any(line.contributions for line in self.lines):
            raise ValueError("A saved recipe request takes its contributions from the saved plan")
        return self


class Constraint(Model):
    """One customer-stated hard limit (POL-008). Server-written only: it is never a field of
    PurchaseRequest, PrepareRequest or any tool input, so the model and API callers cannot set it."""

    name: str = Field(min_length=1, max_length=120)
    value: Money | bool
    source: Literal["user_request", "reviewed_plan", "stated_assumption", "scheduled_request"]
    confirmed: bool

    @model_validator(mode="after")
    def name_matches_value(self):
        if self.name == "budget_gross":
            ok = not isinstance(self.value, bool)
        elif self.name in ("lactose_free", "milk_free") or self.name.startswith("unsupported:"):
            ok = isinstance(self.value, bool)
        else:
            ok = False
        if not ok:
            raise ValueError(f"Unsupported constraint '{self.name}' or value type")
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
    severity: Literal["denied", "unresolved", "exception", "warning"]


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
    # Sales units still missing when stock is below sales_quantity; absent when stock covers it.
    shortfall: str | None = None


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
    contributions: list[dict] | None = None
    price_is_estimate: bool | None = Field(
        default=None,
        description="True for a variable-weight product: the final weight and price settle at "
        "delivery (BAS-007). Absent otherwise.",
    )


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
    totals_are_estimates: bool | None = Field(
        default=None,
        description="True when any line is priced by variable weight, so the totals are "
        "estimates. Absent otherwise.",
    )


class ProposalResponse(Model):
    proposal_id: str
    revision: int
    fingerprint: str = Field(
        description="Fingerprint of this revision's material terms (request, lines, prices, "
        "deposits, product facts, currency, mode, charges, policy version and blockers). A "
        "customer confirmation is bound to this revision and fingerprint; it excludes lookup "
        "time and stock that stays sufficient."
    )
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
    destinations: list[str] = Field(min_length=1)
    substitution: Literal["allowed", "requires_approval", "forbidden"]
    overbuy: Literal["allowed", "requires_approval", "forbidden"]
    whole_sales_units: bool
    approved_product_ids: list[str] | None = Field(
        default=None,
        description="Buyer-configured product scope. Outside products count as substitutions even without an agent flag. Missing scope always blocks a purchase until a policy manager configures it in Settings.",
    )

    @model_validator(mode="before")
    @classmethod
    def ignore_legacy_spend_limit(cls, data):
        """Policy versions stored before Q-35 carry `autonomous_limit`. History is immutable, so
        the key is tolerated and ignored; any other unknown key is still rejected."""
        if isinstance(data, dict) and "autonomous_limit" in data:
            return {k: v for k, v in data.items() if k != "autonomous_limit"}
        return data


class ApproverAuthority(Model):
    """A human approver's limits: the maximum gross amount and the exceptions they may approve."""

    currency: Literal["EUR"]
    max_gross: Money
    exceptions: list[Literal["substitution", "overbuy"]]

    @field_validator("exceptions", mode="before")
    @classmethod
    def ignore_legacy_spend_exception(cls, value):
        """Rows stored before Q-35 list the removed `spend` exception; it is ignored."""
        if isinstance(value, list):
            return [item for item in value if item != "spend"]
        return value


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
    # Units (JNP3-TCT-005): net, gross and available_sales_quantity are all per one sales unit.
    sales_unit: str | None = None
    base_unit: str | None = None
    price_basis: Literal["per_sales_unit"] | None = None
    quantity_unit: str | None = None


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


class ErrorDetail(BaseModel):
    """One validation failure. The submitted value is never included."""

    type: str
    loc: list[str | int]
    msg: str


class ErrorBody(BaseModel):
    """`details` is the list of ErrorDetail for VALIDATION_ERROR; some application errors send an object."""

    code: str
    message: str
    details: list[ErrorDetail] | dict[str, JsonValue] | None = None


class ErrorResponse(BaseModel):
    """The one body of every HTTP error response (TCT-008)."""

    error: ErrorBody
