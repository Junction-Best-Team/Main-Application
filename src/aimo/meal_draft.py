"""Assistant recipe estimates with server-owned scaling, separate from saved recipes."""

from typing import Literal

from pydantic import Field

from aimo.recipe_schemas import Recipe, RecipeIngredient
from aimo.recipes import scaled_plan
from aimo.schemas import MAX_BASKET_LINES, Amount, Model


class DraftIngredient(Model):
    name: str = Field(min_length=1, max_length=240)
    amount: Amount
    unit: Literal["g", "kg", "ml", "l", "piece"]


class DraftRecipe(Model):
    title: str = Field(min_length=1, max_length=240)
    base_servings: int = Field(ge=1, le=10000)
    portions: int = Field(ge=1, le=10000)
    ingredients: list[DraftIngredient] = Field(min_length=1, max_length=MAX_BASKET_LINES)
    notes: list[str] = Field(default_factory=list, max_length=17)
    source: Literal["assistant_estimate", "customer_recipe"] = "assistant_estimate"
    estimated_ingredients: list[str] = Field(default_factory=list, max_length=MAX_BASKET_LINES)


def draft_plan(request):
    recipe = Recipe(
        id="assistant-draft",
        title=request.title,
        summary="Assistant-drafted recipe estimate",
        base_servings=request.base_servings,
        category="draft",
        instructions=[],
        ingredients=[
            RecipeIngredient(
                id=str(index), name=item.name, quantity=item.amount, unit=item.unit, scaling="linear"
            )
            for index, item in enumerate(request.ingredients)
        ],
    )
    plan = scaled_plan(recipe, request.portions)
    plan.notes = [
        ("Customer-supplied recipe, with any added estimates listed separately."
         if request.source == "customer_recipe"
         else "Assistant-drafted recipe estimate, not a recipe retrieved from the saved database."),
        f"Basis: {request.base_servings} servings; server-scaled to {request.portions} portions.",
        "Ingredient quantities and cooking yield are estimates for review, not dietary evidence.",
        *request.notes,
    ]
    if request.estimated_ingredients:
        plan.notes.append("Estimated ingredients: " + ", ".join(request.estimated_ingredients))
    return plan
