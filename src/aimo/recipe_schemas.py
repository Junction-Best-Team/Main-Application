"""Recipe discovery and persisted, evidence-backed meal planning contracts."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from aimo.schemas import Amount, Model


class RecipeSearch(Model):
    query: str = Field(min_length=1, max_length=250)
    category: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=5, ge=1, le=20)


class RecipeReference(Model):
    recipe_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=64)


class ScaleRecipe(RecipeReference):
    portions: int = Field(ge=1, le=10000)


class PlanReference(Model):
    plan_id: UUID


class MatchIngredient(PlanReference):
    revision: int = Field(ge=1)
    ingredient_id: str = Field(min_length=1, max_length=120)
    product_id: str = Field(min_length=1, max_length=40)


class RecipeIngredient(Model):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    quantity: Amount | None = None
    unit: str = Field(min_length=1, max_length=30)
    form: str = Field(default="unspecified", min_length=1, max_length=80)
    scaling: Literal["linear", "damped", "sublinear", "fixed"]
    note: str | None = Field(default=None, max_length=2000)


class Recipe(Model):
    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(max_length=4000)
    base_servings: int = Field(ge=1, le=10000)
    category: str = Field(max_length=80)
    ingredients: list[RecipeIngredient] = Field(min_length=1, max_length=100)
    instructions: list[str] = Field(max_length=100)


class ProductEvidence(Model):
    product_id: str = Field(min_length=1, max_length=40)
    product_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    ingredient_id: str = Field(min_length=1, max_length=120)
    form: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=1000)
    piece_per_sales: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)


class RecipeSummary(Model):
    recipe_id: str
    version: str
    title: str
    summary: str
    base_servings: int


class RecipeSearchResult(Model):
    recipes: list[RecipeSummary]
    rerank_status: Literal["disabled", "applied", "unavailable"]
    note: str


class RecipeDetail(Model):
    recipe: Recipe
    version: str
    source: str
    attribution: str
    license: str
