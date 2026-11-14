"""MEA-014 (Draft, wording pending): several ingredients are matched in one call.

Strict xfails with no implementation. Working reading, to be confirmed with the owner: the
existing single `match_ingredient` stays; a batch form takes the plan reference plus a list of
`{ingredient_id, product_id}` pairs and writes ONE new plan revision. The names below
(`MatchIngredients`, `matches`, `Service.match_ingredients`, tool `match_ingredients`) are
working names, not an agreed interface.
"""

import pytest

from aimo import recipe_schemas
from aimo.service import Service

PLAN = "00000000-0000-4000-8000-000000000001"


@pytest.mark.xfail(
    strict=True,
    reason="MEA-014 Draft: no batch request model; MatchIngredient takes one ingredient",
)
def test_batch_match_request_takes_several_ingredient_product_pairs():
    batch = getattr(recipe_schemas, "MatchIngredients", None)
    assert batch is not None, "recipe_schemas has no MatchIngredients batch request"
    request = batch(
        plan_id=PLAN,
        revision=1,
        matches=[
            {"ingredient_id": "spaghetti", "product_id": "p1"},
            {"ingredient_id": "egg", "product_id": "p2"},
            {"ingredient_id": "pepper", "product_id": "p3"},
        ],
    )
    assert [m.ingredient_id for m in request.matches] == ["spaghetti", "egg", "pepper"]


@pytest.mark.xfail(
    strict=True,
    reason="MEA-014 Draft: Service has match_ingredient only, no batch operation",
)
def test_service_exposes_a_batch_match_operation():
    assert hasattr(Service, "match_ingredients"), "Service.match_ingredients is missing"


@pytest.mark.xfail(
    strict=True,
    reason="MEA-014 Draft: a batch call must write one plan revision, not one per ingredient",
)
def test_batch_match_writes_a_single_new_plan_revision():
    from aimo import recipes

    batch = getattr(recipes, "match_ingredients", None)
    assert batch is not None, "recipes.match_ingredients is missing"
