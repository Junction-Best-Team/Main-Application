"""Shared internal agent and authenticated conversation contracts."""

from datetime import datetime
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


class ChatMessage(Model):
    id: int
    role: Literal["user", "assistant", "system"]  # system: written by the scheduler, not a person
    text: str
    created_at: datetime
    meal_plan: MealPlan | None = None
    proposal_id: str | None = None
    image: RecipeImage | None = None
    attachments: list[AttachmentInfo] = Field(default_factory=list)


class ConversationSummary(Model):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationResponse(ConversationSummary):
    messages: list[ChatMessage]
    purchases: list[ProposalResponse]
    busy: bool = False
    retry_message: RetryMessage | None = None


class ConversationList(Model):
    items: list[ConversationSummary]
    next_offset: int | None = None
