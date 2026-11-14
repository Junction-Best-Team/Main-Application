"""MEA-014 (Approved): the tools backend matches several ingredients in one call.

The single `match_ingredient` stays. `match_ingredients` takes the plan reference plus a list of
`{ingredient_id, product_id}` pairs, writes ONE new plan revision and returns the updated plan.
It is atomic: any invalid pair (unknown ingredient, duplicate ingredient, stale revision, locked
plan) writes nothing. Per-pair semantics are those of `recipes.match_ingredient`: a wrong or
unsuitable product leaves that ingredient unresolved with a reason; it is not an error.

Authored recipe, product and evidence fixtures only (helpers copied from tests/test_recipes.py);
no live supplier call.
"""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aimo import fixtures
from aimo.db import Problem, connection, fingerprint
from aimo.ingest import publish
from aimo.recipe_batch import MAX_BATCH_MATCHES, MatchIngredients, match_ingredients
from aimo.recipe_import import import_product_evidence, ingest_recipes
from aimo.recipe_schemas import MatchIngredient, ScaleRecipe
from aimo.recipes import match_ingredient, scale_recipe
from aimo.service import Service

PLAN = "00000000-0000-4000-8000-000000000001"
IDS = ["spaghetti", "egg", "pepper"]


@pytest.fixture(autouse=True)
def clean_recipes():
    with connection() as c:
        # A recipe reset cascades into guarded history (PER-002): say it is deliberate.
        c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        c.execute(
            "TRUNCATE recipes,recipe_catalogs,recipe_embedding_cache,recipe_product_evidence CASCADE"
        )
    yield


def write(path, data):
    path.write_text(json.dumps(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_recipe(slug="carbonara"):
    # Authored minimal recipe for pipeline testing, not the public UniTools recipe.
    return {
        "slug": slug,
        "name": {"en": "Authored " + slug},
        "summary": {"en": "Pasta meal"},
        "baseServings": 2,
        "category": "main",
        "steps": [{"text": {"en": "Cook the meal."}}],
        "ingredients": [
            {"id": "spaghetti", "name": {"en": "Dry spaghetti"}, "quantity": 200, "unit": "g"},
            {"id": "egg", "name": {"en": "Raw whole eggs"}, "quantity": 1, "unit": "piece"},
            {"id": "pepper", "name": {"en": "Black pepper"}, "quantity": 2, "unit": "g"},
        ],
    }


def import_fixture(tmp_path):
    row = source_recipe()
    for ingredient in row["ingredients"]:
        ingredient["scaling"] = "linear"
    path = tmp_path / "recipes.json"
    sha = write(
        path,
        {
            "license": "CC BY-SA 4.0",
            "version": "authored-test-v1",
            "attribution": "Authored test fixture",
            "recipes": [row],
        },
    )
    reviews = tmp_path / "reviews.json"
    write(
        reviews,
        {
            "source": "Authored test recipe review",
            "recipes": {
                row["slug"]: {
                    "ingredients": {
                        i["id"]: {"form": "raw" if i["id"] == "egg" else "dry"}
                        for i in row["ingredients"]
                    }
                }
            },
        },
    )
    result = ingest_recipes(path, sha, reviews)
    with connection() as c:
        return c.execute(
            "SELECT recipe_id,version FROM recipe_catalog_entries WHERE catalog_id=%s",
            (result["catalog_id"],),
        ).fetchall()


@pytest.fixture
def actor(agent):
    return agent | {"_turn_id": str(uuid4())}


@pytest.fixture
def meal_products(monkeypatch, tmp_path):
    original = fixtures.fixture_facts()
    products = []
    for iid, weight in [("spaghetti", "3"), ("egg", "1"), ("pepper", ".21")]:
        p = deepcopy(original[0])
        p.update(
            id="recipe-" + iid,
            name="Authored " + iid,
            names={"en": "Authored " + iid},
            sales_unit="ST",
            base_unit="ST",
            units={"ST": "1"},
            order_step=".01",
            variable_weight=False,
            deposits=[],
            allergens={},
            claims=[],
            free_from=[],
            measures={
                "KG": {"status": "known", "value": weight, "basis": ["authored.structured.weight"]},
                "L": {"status": "unknown", "value": None, "basis": []},
            },
        )
        products.append(p)
    monkeypatch.setattr(fixtures, "fixture_facts", lambda: original + products)
    publish(original + products, "authored-recipe-products", fingerprint(products))
    rows = [
        dict(
            product_id=p["id"],
            product_fingerprint=fingerprint(p),
            ingredient_id=iid,
            form="raw" if iid == "egg" else "dry",
            source="Authored reviewed product evidence",
            piece_per_sales="30" if iid == "egg" else None,
        )
        for iid, p in zip(IDS, products)
    ]
    evidence = tmp_path / "evidence.json"
    write(evidence, rows)
    import_product_evidence(evidence)
    yield products
    publish(original, "restore-standard-fixtures", fingerprint(original))


def new_plan(tmp_path, actor):
    versions = import_fixture(tmp_path)
    return scale_recipe(actor, ScaleRecipe(**versions[0], portions=200))


def another_plan(actor):
    with connection() as c:
        version = c.execute("SELECT recipe_id,version FROM recipe_catalog_entries").fetchone()
    # One plan per customer turn: a new turn id gives an independent plan.
    return scale_recipe(actor | {"_turn_id": str(uuid4())}, ScaleRecipe(**version, portions=200))


def pairs(**overrides):
    chosen = {i: "recipe-" + i for i in IDS} | overrides
    return [{"ingredient_id": i, "product_id": chosen[i]} for i in IDS]


def batch(plan, matches, revision=None):
    return MatchIngredients(
        plan_id=plan["recipe_plan_id"],
        revision=revision or plan["recipe_plan_revision"],
        matches=matches,
    )


def revision_count(plan):
    with connection() as c:
        return c.execute(
            "SELECT count(*) AS n FROM recipe_plan_revisions WHERE plan_id=%s",
            (plan["recipe_plan_id"],),
        ).fetchone()["n"]


def single_match_all(actor, plan, matches):
    for pair in matches:
        plan = match_ingredient(
            actor,
            MatchIngredient(
                plan_id=plan["recipe_plan_id"],
                revision=plan["recipe_plan_revision"],
                **pair,
            ),
        )
    return plan


def test_batch_match_request_takes_several_ingredient_product_pairs():
    request = MatchIngredients(
        plan_id=PLAN,
        revision=1,
        matches=[
            {"ingredient_id": "spaghetti", "product_id": "p1"},
            {"ingredient_id": "egg", "product_id": "p2"},
            {"ingredient_id": "pepper", "product_id": "p3"},
        ],
    )
    assert [m.ingredient_id for m in request.matches] == ["spaghetti", "egg", "pepper"]


def test_batch_match_request_rejects_empty_oversized_malformed_and_extra_fields():
    pair = {"ingredient_id": "egg", "product_id": "p"}
    assert MAX_BATCH_MATCHES == 1000
    with pytest.raises(ValidationError):
        MatchIngredients(plan_id=PLAN, revision=1, matches=[])
    MatchIngredients(plan_id=PLAN, revision=1, matches=[pair] * MAX_BATCH_MATCHES)
    with pytest.raises(ValidationError):
        MatchIngredients(plan_id=PLAN, revision=1, matches=[pair] * (MAX_BATCH_MATCHES + 1))
    with pytest.raises(ValidationError):
        MatchIngredients(plan_id=PLAN, revision=0, matches=[pair])
    with pytest.raises(ValidationError):
        MatchIngredients(plan_id="not-a-uuid", revision=1, matches=[pair])
    with pytest.raises(ValidationError):
        MatchIngredients(plan_id=PLAN, revision=1, matches=[pair | {"ingredient_id": ""}])
    with pytest.raises(ValidationError):
        MatchIngredients(plan_id=PLAN, revision=1, matches=[pair | {"extra": 1}])
    with pytest.raises(ValidationError):
        MatchIngredients(plan_id=PLAN, revision=1, matches=[pair], extra=1)


def test_service_exposes_a_batch_match_operation():
    assert callable(Service.match_ingredients)


def test_batch_match_writes_one_revision_and_equals_sequential_matching(
    tmp_path, actor, meal_products
):
    plan = new_plan(tmp_path, actor)
    before = revision_count(plan)
    assert plan["recipe_plan_revision"] == 1
    result = match_ingredients(actor, batch(plan, pairs()))
    assert result["recipe_plan_revision"] == 2
    assert revision_count(plan) == before + 1
    with connection() as c:
        stored = c.execute(
            "SELECT revision FROM recipe_plans WHERE id=%s", (plan["recipe_plan_id"],)
        ).fetchone()
    assert stored["revision"] == 2
    assert [i["status"] for i in result["ingredients"]] == ["matched"] * 3


def test_batch_result_equals_one_by_one_matching_on_a_second_plan(tmp_path, actor, meal_products):
    first = new_plan(tmp_path, actor)
    second = another_plan(actor)  # a second, independent plan of the same recipe version
    assert first["recipe_plan_id"] != second["recipe_plan_id"]
    matches = pairs()
    by_batch = match_ingredients(actor, batch(first, matches))
    by_single = single_match_all(actor, second, matches)
    assert by_batch["recipe_plan_revision"] == 2
    assert by_single["recipe_plan_revision"] == 4  # one revision per ingredient
    assert by_batch["ingredients"] == by_single["ingredients"]


def test_wrong_product_leaves_only_that_ingredient_unresolved(tmp_path, actor, meal_products):
    plan = new_plan(tmp_path, actor)
    before = revision_count(plan)
    result = match_ingredients(actor, batch(plan, pairs(spaghetti="recipe-egg")))
    status = {i["ingredient_id"]: i for i in result["ingredients"]}
    assert status["spaghetti"]["status"] == "unresolved"
    assert status["spaghetti"]["reason"]
    assert status["spaghetti"]["product_id"] is None
    assert status["egg"]["status"] == status["pepper"]["status"] == "matched"
    assert revision_count(plan) == before + 1
    # Same outcome as matching that same wrong pair on its own.
    second = another_plan(actor)
    single = single_match_all(actor, second, pairs(spaghetti="recipe-egg"))
    # Both paths record the refused product (MEA-005 "selections"); everything else is identical.
    rejected = status["spaghetti"].pop("rejected")
    assert [r["product_id"] for r in rejected] == ["recipe-egg"] and rejected[0]["reason"]
    assert [r["product_id"] for r in single["ingredients"][0]["rejected"]] == ["recipe-egg"]

    def bare(items):
        return [{k: v for k, v in i.items() if k != "rejected"} for i in items]

    assert bare(result["ingredients"]) == bare(single["ingredients"])


def test_absent_product_is_unresolved_not_an_error(tmp_path, actor, meal_products):
    plan = new_plan(tmp_path, actor)
    result = match_ingredients(actor, batch(plan, pairs(pepper="no-such-product")))
    pepper = result["ingredients"][2]
    assert pepper["status"] == "unresolved"
    assert "absent" in pepper["reason"]


def test_partial_batch_changes_only_named_ingredients(tmp_path, actor, meal_products):
    plan = new_plan(tmp_path, actor)
    result = match_ingredients(actor, batch(plan, pairs()[:1]))
    assert [i["status"] for i in result["ingredients"]] == ["matched", "unresolved", "unresolved"]
    assert result["recipe_plan_revision"] == 2


def test_stale_revision_is_rejected_and_writes_nothing(tmp_path, actor, meal_products):
    plan = new_plan(tmp_path, actor)
    match_ingredients(actor, batch(plan, pairs()[:1]))
    before = revision_count(plan)
    with pytest.raises(Problem) as error:
        match_ingredients(actor, batch(plan, pairs(), revision=1))
    assert error.value.code == "RECIPE_PLAN_CHANGED"
    assert revision_count(plan) == before


def test_unknown_ingredient_rejects_the_whole_batch_and_writes_nothing(
    tmp_path, actor, meal_products
):
    plan = new_plan(tmp_path, actor)
    before = revision_count(plan)
    matches = pairs() + [{"ingredient_id": "saffron", "product_id": "recipe-pepper"}]
    with pytest.raises(Problem) as error:
        match_ingredients(actor, batch(plan, matches))
    assert error.value.code == "INGREDIENT_UNKNOWN"
    assert revision_count(plan) == before
    with connection() as c:
        stored = c.execute(
            "SELECT revision FROM recipe_plans WHERE id=%s", (plan["recipe_plan_id"],)
        ).fetchone()
    assert stored["revision"] == 1


def test_duplicate_ingredient_in_a_batch_is_rejected_and_writes_nothing(
    tmp_path, actor, meal_products
):
    plan = new_plan(tmp_path, actor)
    before = revision_count(plan)
    matches = pairs() + [{"ingredient_id": "egg", "product_id": "recipe-spaghetti"}]
    with pytest.raises(Problem) as error:
        match_ingredients(actor, batch(plan, matches))
    assert error.value.status == 422
    assert error.value.code == "INGREDIENT_DUPLICATE"
    assert revision_count(plan) == before


def test_locked_plan_is_rejected_and_writes_nothing(tmp_path, actor, meal_products):
    plan = new_plan(tmp_path, actor)
    with connection() as c:
        c.execute("UPDATE recipe_plans SET locked=true WHERE id=%s", (plan["recipe_plan_id"],))
    before = revision_count(plan)
    with pytest.raises(Problem) as error:
        match_ingredients(actor, batch(plan, pairs()))
    assert error.value.code == "RECIPE_PLAN_LOCKED"
    assert revision_count(plan) == before


def test_another_agents_plan_is_not_found(tmp_path, actor, meal_products):
    plan = new_plan(tmp_path, actor)
    with pytest.raises(Problem) as error:
        match_ingredients(actor | {"id": "other-agent"}, batch(plan, pairs()))
    assert error.value.code in {"NOT_FOUND", "AUTHORITY_REVOKED"}
    assert revision_count(plan) == 1


def test_service_batch_operation_writes_one_revision(tmp_path, actor, service, meal_products):
    plan = new_plan(tmp_path, actor)
    request = batch(plan, pairs())
    result = service.match_ingredients(actor, request)
    assert result["recipe_plan_revision"] == 2
