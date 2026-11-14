"""MEA-005: a refused product choice is kept with its reason, but only the newest 100 (schema cap).

`Ingredient.rejected` holds at most 100 entries (chat_schemas). Before this fix both append paths
(`recipes.match_ingredient` and `recipe_batch.match_ingredients`) grew the list without a cap, so
the 101st refusal of one ingredient made `get_recipe_plan` fail with TOOL_RESULT_INVALID 502.
Each path keeps the newest 100, in order. Authored fixtures only.
"""

import json

import pytest
import test_recipe_arithmetic as arithmetic
from test_recipe_arithmetic import import_fixture, match, ref

from aimo.agent_tools import ToolSession
from aimo.chat_schemas import MealPlan
from aimo.recipe_batch import IngredientMatch, MatchIngredients, match_ingredients
from aimo.recipes import scale_recipe

actor = arithmetic.actor
clean_recipes = arithmetic.clean_recipes
meal_products = arithmetic.meal_products

WRONG = ["recipe-egg", "recipe-pepper"]  # neither fits the spaghetti ingredient


def refuse_single(a, plan, product_id):
    return match(a, plan, "spaghetti", product_id)


def refuse_batch(a, plan, product_id):
    return match_ingredients(
        a,
        MatchIngredients(
            plan_id=plan["recipe_plan_id"],
            revision=plan["recipe_plan_revision"],
            matches=[IngredientMatch(ingredient_id="spaghetti", product_id=product_id)],
        ),
    )


@pytest.mark.parametrize("count", [100, 101, 250])
@pytest.mark.parametrize("refuse", [refuse_single, refuse_batch], ids=["single", "batch"])
def test_only_the_newest_hundred_refusals_are_kept_in_order_and_the_plan_stays_readable(
    tmp_path, actor, service, meal_products, count, refuse
):
    plan = scale_recipe(actor, ref(import_fixture(tmp_path)))
    sequence = [WRONG[n % 2] for n in range(count)]
    for product_id in sequence:
        plan = refuse(actor, plan, product_id)
    kept = plan["ingredients"][0]["rejected"]
    assert [r["product_id"] for r in kept] == sequence[-100:]
    assert len(kept) == min(count, 100)
    assert all(r["reason"] == plan["ingredients"][0]["reason"] for r in kept)
    # the plan is still valid for the model and readable through the tool
    MealPlan.model_validate(plan)
    session = ToolSession(actor, service)
    result = session.invoke("get_recipe_plan", json.dumps({"plan_id": plan["recipe_plan_id"]}))
    assert len(result["meal_plan"]["ingredients"][0]["rejected"]) == min(count, 100)


def test_the_two_paths_agree_on_what_they_keep(tmp_path, actor, meal_products):
    single = scale_recipe(actor, ref(import_fixture(tmp_path)))
    for n in range(103):
        single = refuse_single(actor, single, WRONG[n % 2])
    batched = scale_recipe(actor | {"_turn_id": "other-turn"}, ref(import_fixture(tmp_path)))
    for n in range(103):
        batched = refuse_batch(actor | {"_turn_id": "other-turn"}, batched, WRONG[n % 2])
    assert [r["product_id"] for r in single["ingredients"][0]["rejected"]] == [
        r["product_id"] for r in batched["ingredients"][0]["rejected"]
    ]
