"""Shared internal agent and authenticated conversation contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from aimo.image_schemas import RecipeImage
from aimo.schemas import Model, ProposalResponse, QuantityCalculation


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
    rejected: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class MealPlan(Model):
    title: str = Field(min_length=1, max_length=240)
    portions: int = Field(ge=1, le=10000)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=1000)
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


class MessageRequest(Model):
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=120)


class ConversationCreate(Model):
    title: str = Field(default="New purchase", min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=120)


class ChatMessage(Model):
    id: int
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
    meal_plan: MealPlan | None = None
    proposal_id: str | None = None
    image: RecipeImage | None = None


class ConversationSummary(Model):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationResponse(ConversationSummary):
    messages: list[ChatMessage]
    purchases: list[ProposalResponse]
    busy: bool = False
    retry_message: MessageRequest | None = None


class ConversationList(Model):
    items: list[ConversationSummary]
    next_offset: int | None = None
