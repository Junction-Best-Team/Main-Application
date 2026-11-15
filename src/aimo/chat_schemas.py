"""Shared internal agent and authenticated conversation contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from aimo.attachments import AttachmentInfo, AttachmentInput, check_total
from aimo.image_schemas import RecipeImage
from aimo.schemas import MAX_BASKET_LINES, Constraint, Model, ProposalResponse, QuantityCalculation

# MEA-005: the newest refused product choices kept per ingredient (every append path trims to it).
MAX_REJECTED = 100


class Ingredient(Model):
    name: str = Field(min_length=1, max_length=240)
    amount: str | None = Field(default=None, min_length=1, max_length=30)
    unit: str = Field(min_length=1, max_length=30)
    product_id: str | None = None
    ingredient_id: str | None = None
    form: str | None = None
    status: Literal["proposed", "matched", "unresolved"] = "proposed"
    reason: str | None = None
    purchase_amount: str | None = Field(
        default=None,
        description="The REQUIRED amount in the unit the basket uses (a copy of amount, converted "
        "to the plan unit). It is not the pack-rounded purchase: see conversion.proposed_amount.",
    )
    purchase_unit: str | None = Field(
        default=None,
        description="Unit of purchase_amount (KG, L or piece). Not the pack or sales unit.",
    )
    product_fingerprint: str | None = None
    conversion: QuantityCalculation | None = None
    rejected: list[dict[str, str]] = Field(default_factory=list, max_length=MAX_REJECTED)


class MealPlan(Model):
    title: str = Field(min_length=1, max_length=240)
    portions: int = Field(ge=1, le=10000)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=MAX_BASKET_LINES)
    notes: list[str] = Field(default_factory=list, max_length=20)
    # Catalog cooking steps for display only (untrusted recipe text, not policy).
    instructions: list[str] = Field(default_factory=list, max_length=100)
    recipe_plan_id: str | None = None
    recipe_plan_revision: int | None = None
    recipe_id: str | None = None
    recipe_version: str | None = None
    base_servings: int | None = None
    attribution: str | None = None


class AgentTurn(Model):
    text: str = Field(min_length=1, max_length=20000)
    meal_plan: MealPlan | None = None
    proposal_id: str | None = None
    image: RecipeImage | None = None


class MessageConstraints(Model):
    """Hard limits the customer sets on a message (POL-008); false withdraws an earlier toggle."""

    budget_gross: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=4)] | None = Field(
        default=None, description="Hard budget in euros, gross; the basket may not exceed it."
    )
    lactose_free: bool | None = Field(default=None, description="Require lactose-free products.")
    milk_free: bool | None = Field(default=None, description="Require milk-free products.")

    @model_validator(mode="after")
    def says_something(self):
        if self.budget_gross is None and self.lactose_free is None and self.milk_free is None:
            raise ValueError("Set at least one limit, or omit the field")
        return self

    def records(self):
        """The trusted constraint records (source user_request, confirmed) for these fields."""
        values = {
            "budget_gross": self.budget_gross,
            "lactose_free": self.lactose_free,
            "milk_free": self.milk_free,
        }
        return [
            Constraint(name=name, value=value, source="user_request", confirmed=True).model_dump(
                mode="json"
            )
            for name, value in values.items()
            if value is not None
        ]


class MessageRequest(Model):
    text: str = Field(default="", max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    constraints: MessageConstraints | None = Field(
        default=None,
        description="Optional hard limits set by the customer (budget, dietary toggles). They "
        "stay in force for the rest of the conversation until a later message changes them.",
    )
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_message(self):
        if not self.text.strip() and not self.attachments:
            raise ValueError("Write a message or attach a file.")
        check_total(self.attachments)
        return self


class EditMessageRequest(Model):
    """Replace a persisted user message's text and regenerate from that point."""

    text: str = Field(max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=120)

    @model_validator(mode="after")
    def validate_message(self):
        if not self.text.strip():
            raise ValueError("Write a message or attach a file.")
        return self


class RetryConstraints(Model):
    """The limits of an unfinished message, in the shape the client sends them back."""

    budget_gross: str | None = None
    lactose_free: bool | None = None
    milk_free: bool | None = None


class RetryMessage(Model):
    """An unfinished message, including the same limits and files for an exact retry."""

    text: str
    idempotency_key: str
    constraints: RetryConstraints | None = None
    attachments: list[AttachmentInput] = Field(default_factory=list)


class ConversationCreate(Model):
    title: str = Field(default="New purchase", min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=120)


class CartPurchaseRequest(Model):
    """Prepare the order from the conversation's cart without the assistant (a customer button)."""

    delivery_date: date
    destination: str = Field(min_length=1, max_length=120)
    request_id: str = Field(
        min_length=8,
        max_length=120,
        description="Idempotency key: one per button press, reused when the press is retried.",
    )


class CartRefreshRequest(Model):
    """Prepare an EXPIRED basket again from the cart, for the same date and destination (a button)."""

    request_id: str = Field(
        min_length=8,
        max_length=120,
        description="Idempotency key: one per button press, reused when the press is retried.",
    )


class CartNotIncluded(Model):
    name: str
    amount: str | None
    unit: str
    reason: Literal["no_product", "no_quantity", "removed"]


class CartLineEdit(Model):
    product_id: str = Field(min_length=1, max_length=40)
    sales_quantity: int = Field(
        strict=True,
        ge=0,
        le=100000,
        description="Whole sales units (packs) of this product in the basket. 0 leaves the line out "
        "of the basket but keeps the product in the cart, so a later value above 0 brings it back.",
    )


class CartEditRequest(Model):
    """The customer's own quantity edit on the card: only products already in the cart."""

    request_id: str = Field(
        min_length=8,
        max_length=120,
        description="Idempotency key: one per edit, reused when the edit is retried.",
    )
    lines: list[CartLineEdit] = Field(min_length=1, max_length=MAX_BASKET_LINES)

    @model_validator(mode="after")
    def one_edit_per_product(self):
        ids = [line.product_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Send one edit per product")
        return self


class CartPurchaseResponse(Model):
    proposal: ProposalResponse
    not_included: list[CartNotIncluded]


class ChatMessage(Model):
    id: int
    role: Literal["user", "assistant", "system"]  # system: written by the scheduler, not a person
    text: str
    created_at: datetime
    meal_plan: MealPlan | None = None
    proposal_id: str | None = None
    image: RecipeImage | None = None
    attachments: list[AttachmentInfo] = Field(default_factory=list)
    notice: Literal["provider_unavailable", "order_confirmed"] | None = Field(
        default=None,
        description="Set on a plain notice, not an answer. provider_unavailable: stored when the "
        "model provider failed (the unfinished message keeps its retry offer). order_confirmed "
        "(role system): one line stored after the customer's confirm placed a demo order, in the "
        "customer's language, with the delivery date.",
    )


class ConversationSummary(Model):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatActivityEvent(Model):
    sequence: int = Field(ge=1, le=640)
    kind: Literal[
        "started",
        "thinking",
        "tool_started",
        "tool_completed",
        "tool_failed",
        "reviewing",
        "complete",
        "error",
    ]
    label: str = Field(min_length=1, max_length=80)
    # Completed tools only: a server-built summary of the validated result (recipe or product
    # names, counts, mock basket totals). Never model arguments, prose or provider errors.
    detail: str | None = Field(default=None, max_length=160)


class ChatActivity(Model):
    turn_id: str
    state: Literal["queued", "running", "complete", "failed"]
    events: list[ChatActivityEvent] = Field(default_factory=list, max_length=600)


class DraftPrice(Model):
    gross: str
    currency: str
    sales_unit: str
    mode: str
    delivery_date: str
    observed_at: datetime
    expires_at: datetime


class DraftCartItem(Model):
    name: str
    amount: str | None
    unit: str
    product_id: str | None = None
    product_name: str | None = None
    matched: bool = False
    price: DraftPrice | None = None


class DraftCart(Model):
    """Display-only plan projection; never accepted by confirmation or preparation."""

    turn_id: str
    title: str
    items: list[DraftCartItem] = Field(min_length=1, max_length=MAX_BASKET_LINES)
    proposal_id: str | None = None


class ConversationResponse(ConversationSummary):
    messages: list[ChatMessage]
    purchases: list[ProposalResponse]
    busy: bool = False
    activity: ChatActivity | None = None
    draft_cart: DraftCart | None = None
    cart_not_included: list[CartNotIncluded] = Field(
        default_factory=list,
        description="Items the current basket leaves out (no product, no quantity, or removed by "
        "the customer on the card), from the latest stored plan; empty without an open basket.",
    )
    cart_editable: bool = False
    cart_edit_reason: str | None = Field(
        default=None, description="Why the number controls on the card are disabled, if they are."
    )
    retry_message: RetryMessage | None = None


class ConversationList(Model):
    items: list[ConversationSummary]
    next_offset: int | None = None
