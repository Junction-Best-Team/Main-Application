"""Verification package for JNP3-MEA-001..009 (recipe scaling, matching and basket evidence).

Pure tests call `aimo.recipes.scaled_plan` directly. The conftest still opens the test database
for every module, but these tests read and write nothing there. DB tests use authored recipe and
product fixtures only (copied helpers from tests/test_recipes.py); no live supplier call.
Strict xfail tests mark requirement gaps: they must fail today for the stated reason and turn into
failures (XPASS) when the gap is closed, which is the signal to remove the marker.
MEA-010 (constraint provenance) has no API to call; its proving test is in the evidence file.
"""

import ast
import hashlib
import json
import random
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aimo import fixtures
from aimo.agent_tools import ToolSession
from aimo.catalog import quantity
from aimo.db import Problem, connection, fingerprint
from aimo.ingest import publish
from aimo.recipe_import import import_product_evidence, ingest_recipes
from aimo.recipe_schemas import MatchIngredient, Recipe, ScaleRecipe
from aimo.recipes import match_ingredient, scale_recipe, scaled_plan
from aimo.schemas import PrepareRequest

SRC = Path(__file__).resolve().parents[1] / "src" / "aimo"


# --- pure helpers -------------------------------------------------------------------------------


def make_recipe(items, base=4, title="Authored dish"):
    ingredients = []
    for i, (quantity_, unit, scaling) in enumerate(items):
        ingredients.append(
            dict(
                id=f"i{i}",
                name=f"n{i}",
                quantity=quantity_,
                unit=unit,
                form="raw",
                scaling=scaling,
            )
        )
    return Recipe.model_validate(
        dict(
            id="x",
            title=title,
            summary="",
            base_servings=base,
            category="x",
            instructions=[],
            ingredients=ingredients,
        )
    )


def one(quantity_, unit, base, portions, scaling="linear"):
    plan = scaled_plan(make_recipe([(quantity_, unit, scaling)], base=base), portions)
    return plan.ingredients[0]


# --- MEA-003: deterministic arithmetic ----------------------------------------------------------


@pytest.mark.parametrize(
    "quantity_, unit, base, portions, amount, out_unit",
    [
        (200, "g", 4, 200, "10", "KG"),
        (150, "g", 4, 200, "7.5", "KG"),
        (500, "g", 4, 200, "25", "KG"),
        (3, "piece", 4, 200, "150", "piece"),
        (2, "kg", 4, 10, "5", "KG"),
        (500, "ml", 4, 8, "1", "L"),
        (1, "l", 3, 6, "2", "L"),
        ("0.5", "kg", 2, 1, "0.25", "KG"),
    ],
)
def test_exact_scaled_values(quantity_, unit, base, portions, amount, out_unit):
    item = one(quantity_, unit, base, portions)
    assert (item.amount, item.unit) == (amount, out_unit)


def test_scaled_plan_is_a_pure_function_of_recipe_and_portions():
    recipe = make_recipe([(200, "g", "linear"), (3, "piece", "linear"), (1, "tbsp", "damped")])
    before = recipe.model_dump(mode="json")
    first = scaled_plan(recipe, 200).model_dump(mode="json")
    second = scaled_plan(recipe, 200).model_dump(mode="json")
    assert first == second
    assert recipe.model_dump(mode="json") == before  # input never mutated
    assert scaled_plan(recipe, 100).model_dump(mode="json") != first


UNIT_FACTOR = {
    "g": (Fraction(1, 1000), "KG"),
    "kg": (Fraction(1), "KG"),
    "ml": (Fraction(1, 1000), "L"),
    "l": (Fraction(1), "L"),
    "piece": (Fraction(1), "piece"),
}


def oracle(quantity_, unit, base, portions):
    """Independent expectation (MEA-012): exact value rounded UP to four decimals, None above 14 digits."""
    factor, out_unit = UNIT_FACTOR[unit]
    value = Fraction(Decimal(quantity_)) * portions / base * factor
    rounded = Fraction(-((-value.numerator * 10_000) // value.denominator), 10_000)  # ceiling
    for places in range(5):
        scaled = rounded * 10**places
        if scaled.denominator == 1:
            digits = len(str(scaled.numerator))
            return (rounded, out_unit) if digits <= 14 else (None, out_unit)
    raise AssertionError("a four-decimal value always has at most four places")


def test_property_every_amount_equals_the_exact_fraction_or_is_unresolved():
    rng = random.Random(20261114)
    quantities = [
        "1",
        "2",
        "3",
        "7",
        "0.5",
        "12.25",
        "100",
        "150",
        "333",
        "0.0001",
        "99999.9999",
        "9999999999.9999",
    ]
    checked = nulls = 0
    for _ in range(1500):
        quantity_ = rng.choice(quantities)
        unit = rng.choice(list(UNIT_FACTOR))
        base = rng.choice([1, 2, 3, 4, 6, 7, 8, 12, 25, 100, 9999, 10000])
        portions = rng.choice([1, 2, 3, 7, 50, 100, 200, 1000, 9999, 10000])
        expected, out_unit = oracle(quantity_, unit, base, portions)
        item = one(quantity_, unit, base, portions)
        assert item.unit == out_unit
        if expected is None:
            assert item.amount is None, (quantity_, unit, base, portions, item.amount)
            assert "precision" in item.reason
            nulls += 1
        else:
            assert Fraction(Decimal(item.amount)) == expected, (quantity_, unit, base, portions)
            assert item.reason == "Match a suitable catalog product."
        checked += 1
    assert checked == 1500 and 0 < nulls < checked  # both branches were exercised


def test_non_terminating_results_are_rounded_up_never_down():
    # MEA-012: 100 g / 3 servings * 1 portion = 0.0333... KG becomes 0.0334 (ceiling, not half-up).
    item = one(100, "g", 3, 1)
    assert item.amount == "0.0334" and item.unit == "KG"
    assert item.reason == "Match a suitable catalog product."
    # Base 6 / 200 portions: 150 g is exact (5 KG) and untouched; 200 g is 100/3 KG, rounded up.
    assert one(150, "g", 6, 200).amount == "5"
    assert one(200, "g", 6, 200).amount == "6.6667"


def test_fifteen_digit_results_are_unresolved():
    # Recipe.quantity is at most 14 digits (10 whole, 4 decimals); scaling can exceed that.
    assert one("9999999999.9999", "kg", 1, 1).amount == "9999999999.9999"
    assert one("9999999999.9999", "kg", 1, 3).amount is None  # 29999999999.9997 has 15 digits


def test_scaled_plan_module_uses_no_float():
    tree = ast.parse((SRC / "recipes.py").read_text())
    floats = [
        n
        for n in ast.walk(tree)
        if (isinstance(n, ast.Constant) and isinstance(n.value, float))
        or (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "float")
    ]
    assert floats == []


# --- MEA-002: units and serving basis are validated before scaling -------------------------------


@pytest.mark.parametrize("base", [0, -1, 10001])
def test_recipe_with_invalid_serving_basis_is_rejected_by_the_model(base):
    with pytest.raises(ValidationError):
        make_recipe([(1, "g", "linear")], base=base)


@pytest.mark.parametrize("portions", [0, -1, 10001])
def test_invalid_portion_count_is_rejected_before_any_scaling(portions):
    with pytest.raises(ValidationError):
        ScaleRecipe(recipe_id="r", version="v", portions=portions)


def test_unsupported_unit_is_unresolved_with_a_reason_and_keeps_its_unit():
    item = one(1, "tbsp", 4, 200)
    assert item.amount is None and item.unit == "tbsp" and item.status == "unresolved"
    assert (
        item.reason
        == "Recipe unit needs an ingredient-specific conversion to mass, volume or count."
    )


@pytest.mark.parametrize("unit", ["KG", "G", "Kg", "kg ", "slice", "dl", "toTaste"])
def test_unit_names_are_matched_exactly_and_everything_else_is_unresolved(unit):
    item = one(1, unit, 1, 1)
    assert item.amount is None and "conversion" in item.reason


@pytest.mark.parametrize("scaling", ["damped", "sublinear", "fixed"])
def test_non_linear_scaling_is_never_guessed(scaling):
    item = one(100, "g", 4, 200, scaling=scaling)
    assert item.amount is None and "reviewed scaling rule" in item.reason


def test_missing_quantity_is_unresolved_with_a_reason():
    item = one(None, "toTaste", 4, 200, scaling="fixed")
    assert item.amount is None and "unspecified" in item.reason


def test_one_thousand_ingredients_scale_and_more_are_refused():
    ok = make_recipe([(1, "g", "linear")] * 1000)
    assert len(scaled_plan(ok, 10).ingredients) == 1000
    # The Recipe model already refuses more than 1000; scaled_plan stays a second line of defence.
    too_big = ok.model_copy(update={"ingredients": ok.ingredients + ok.ingredients[:1]})
    with pytest.raises(Problem) as error:
        scaled_plan(too_big, 10)
    assert error.value.code == "RECIPE_TOO_LARGE"


# --- MEA-004: base quantities versus already scaled quantities ------------------------------------


def test_feeding_scaled_amounts_back_as_a_recipe_is_the_only_way_to_scale_twice():
    recipe = make_recipe([(200, "g", "linear")], base=4)
    plan = scaled_plan(recipe, 200)
    assert plan.ingredients[0].amount == "10" and plan.base_servings == 4 and plan.portions == 200
    # Hand-built recipe from the plan's amounts, with the plan's portions as its serving basis.
    twice = scaled_plan(make_recipe([("10", "kg", "linear")], base=plan.portions), 200)
    assert twice.ingredients[0].amount == "10"  # correct reading: base = 200 portions
    wrong = scaled_plan(make_recipe([("10", "kg", "linear")], base=plan.base_servings), 200)
    assert wrong.ingredients[0].amount == "500"  # 50x too much: this is what double scaling is
    assert wrong.ingredients[0].amount != plan.ingredients[0].amount


def test_scaled_plan_has_exactly_one_caller_and_it_passes_a_stored_recipe_version():
    calls = []
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "scaled_plan":
                calls.append((path.name, ast.unparse(node)))
    assert calls == [
        (
            "recipes.py",
            "scaled_plan(Recipe.model_validate(detail['recipe']), request.portions)",
        )
    ]
    source = (SRC / "recipes.py").read_text()
    # `detail` is get_recipe(): the immutable recipe_versions row, never a recipe_plans row.
    assert "detail = get_recipe(identity, request)" in source


# --- DB helpers (copied from tests/test_recipes.py, reduced) --------------------------------------


@pytest.fixture(autouse=True)
def clean_recipes():
    with connection() as c:
        c.execute(
            "TRUNCATE recipes,recipe_catalogs,recipe_embedding_cache,recipe_product_evidence CASCADE"
        )
    yield


def write(path, data):
    path.write_text(json.dumps(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_recipe(slug="carbonara", base=2):
    ingredient = lambda iid, name, quantity_, unit: dict(  # noqa: E731
        id=iid, name={"en": name}, quantity=quantity_, unit=unit, scaling="linear"
    )
    return {
        "slug": slug,
        "name": {"en": "Authored " + slug},
        "summary": {"en": "Pasta meal"},
        "baseServings": base,
        "category": "main",
        "steps": [{"text": {"en": "Cook the meal."}}],
        "ingredients": [
            ingredient("spaghetti", "Dry spaghetti", 200, "g"),
            ingredient("egg", "Raw whole eggs", 1, "piece"),
            ingredient("pepper", "Black pepper", 2, "g"),
        ],
    }


def import_fixture(tmp_path, rows=None, review=True, overrides=None):
    rows = rows or [source_recipe()]
    path = tmp_path / "recipes.json"
    sha = write(
        path,
        {
            "license": "CC BY-SA 4.0",
            "version": "authored-test-v1",
            "attribution": "Authored test fixture",
            "recipes": rows,
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
                        | (overrides or {}).get(i["id"], {})
                        for i in row["ingredients"]
                    }
                }
                for row in rows
            },
        },
    )
    result = ingest_recipes(path, sha, reviews if review else None)
    with connection() as c:
        versions = c.execute(
            "SELECT recipe_id,version FROM recipe_catalog_entries WHERE catalog_id=%s ORDER BY recipe_id",
            (result["catalog_id"],),
        ).fetchall()
    return versions


@pytest.fixture
def actor(agent):
    return agent | {"_turn_id": str(uuid4())}


def ref(versions, portions=200):
    return ScaleRecipe(**versions[0], portions=portions)


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
        for iid, p in zip(["spaghetti", "egg", "pepper"], products)
    ]
    evidence = tmp_path / "evidence.json"
    write(evidence, rows)
    import_product_evidence(evidence)
    yield products
    publish(original, "restore-standard-fixtures", fingerprint(original))


def match(actor, plan, ingredient_id, product_id):
    return match_ingredient(
        actor,
        MatchIngredient(
            plan_id=plan["recipe_plan_id"],
            revision=plan["recipe_plan_revision"],
            ingredient_id=ingredient_id,
            product_id=product_id,
        ),
    )


def match_all(actor, plan):
    for item in list(plan["ingredients"]):
        plan = match(actor, plan, item["ingredient_id"], "recipe-" + item["ingredient_id"])
    return plan


def request_for(plan, lines=None):
    return PrepareRequest(
        recipe_plan_id=plan["recipe_plan_id"],
        recipe_plan_revision=plan["recipe_plan_revision"],
        request_id="Authored recipe for 200",
        idempotency_key=str(uuid4()),
        destination="hotel-helsinki",
        delivery_date=date.today() + timedelta(days=2),
        budget_gross="1000",
        lines=lines
        or [
            {
                "product_id": i["product_id"],
                "amount": i["purchase_amount"],
                "unit": i["purchase_unit"],
            }
            for i in plan["ingredients"]
            if i["status"] == "matched"
        ],
    )


def plan_revisions(plan_id):
    with connection() as c:
        rows = c.execute(
            "SELECT revision,data FROM recipe_plan_revisions WHERE plan_id=%s ORDER BY revision",
            (plan_id,),
        ).fetchall()
    return {r["revision"]: r["data"] for r in rows}


def proposal_count():
    with connection() as c:
        return c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"]


def remove_egg_count():
    with connection() as c:
        c.execute(
            "UPDATE recipe_product_evidence SET piece_per_sales=NULL WHERE ingredient_id='egg'"
        )


def shared_product_plan(tmp_path, actor, products):
    """Two ingredients (20 KG and 10 KG of spaghetti) matched to ONE 3 kg product."""
    raw = source_recipe()
    raw["ingredients"] = [
        raw["ingredients"][0],
        dict(
            id="spaghetti2",
            name={"en": "More dry spaghetti"},
            quantity=100,
            unit="g",
            scaling="linear",
        ),
    ]
    spaghetti = products[0]
    rows = [
        dict(
            product_id="recipe-spaghetti",
            product_fingerprint=fingerprint(spaghetti),
            ingredient_id="spaghetti2",
            form="dry",
            source="Authored reviewed product evidence",
            piece_per_sales=None,
        )
    ]
    extra = tmp_path / "extra-evidence.json"
    write(extra, rows)
    import_product_evidence(extra)
    versions = import_fixture(tmp_path, [raw])
    plan = scale_recipe(actor, ref(versions))
    for iid in ["spaghetti", "spaghetti2"]:
        plan = match(actor, plan, iid, "recipe-spaghetti")
    return plan


# --- MEA-001: demonstration, reviewed recipe to exact quantities and product choices -------------


def test_demo_reviewed_recipe_becomes_exact_quantities_and_one_product_per_ingredient(
    tmp_path, actor, service, meal_products
):
    versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    rows = [
        (
            i["ingredient_id"],
            i["amount"],
            i["unit"],
            i["product_id"],
            i["conversion"]["sales_quantity"],
        )
        for i in plan["ingredients"]
    ]
    assert rows == [
        ("spaghetti", "20", "KG", "recipe-spaghetti", "7"),
        ("egg", "100", "piece", "recipe-egg", "4"),
        ("pepper", "0.2", "KG", "recipe-pepper", "1"),
    ]
    prepared = service.prepare_order(actor, request_for(plan))
    lines = {line["product_id"]: line["quantity"] for line in prepared["snapshot"]["lines"]}
    assert {
        k: (v["requested_amount"], v["requested_unit"], v["sales_quantity"])
        for k, v in lines.items()
    } == {
        "recipe-spaghetti": ("20", "KG", "7"),
        "recipe-egg": ("100", "piece", "4"),
        "recipe-pepper": ("0.2", "KG", "1"),
    }
    assert prepared["recipe_basis"] == "saved_recipe" and prepared["order_id"] is None
    print("\nDEMO 200 portions of authored carbonara (base 2):")  # visible with -s
    for iid, amount, unit, product, packs in rows:
        print(f"  {iid:10} {amount:>5} {unit:5} -> {product:17} packs={packs}")
    print(f"  proposal {prepared['proposal_id']} outcome={prepared['policy_outcome']}")


# --- MEA-002 / MEA-004 on the stored recipe path ---------------------------------------------------


def test_import_rejects_a_recipe_with_zero_serving_basis(tmp_path):
    with pytest.raises(ValueError):
        import_fixture(tmp_path, [source_recipe(base=0)])
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM recipes").fetchone()["n"] == 0


def test_new_turn_rescales_from_the_stored_base_not_from_the_saved_plan(tmp_path, actor):
    versions = import_fixture(tmp_path)
    first = scale_recipe(actor, ref(versions))
    assert first["ingredients"][0]["amount"] == "20" and first["base_servings"] == 2
    assert scale_recipe(actor, ref(versions)) == first  # same turn: saved plan returned unchanged
    later = scale_recipe(actor | {"_turn_id": str(uuid4())}, ref(versions))
    assert later["recipe_plan_id"] != first["recipe_plan_id"]
    assert later["ingredients"][0]["amount"] == "20"  # not 2000: computed from the base again
    other = scale_recipe(actor | {"_turn_id": str(uuid4())}, ref(versions, portions=100))
    assert other["ingredients"][0]["amount"] == "10"


def test_matching_never_changes_a_scaled_amount(tmp_path, actor, meal_products):
    versions = import_fixture(tmp_path)
    plan = scale_recipe(actor, ref(versions))
    amounts = [(i["ingredient_id"], i["amount"], i["unit"]) for i in plan["ingredients"]]
    matched = match_all(actor, plan)
    assert [(i["ingredient_id"], i["amount"], i["unit"]) for i in matched["ingredients"]] == amounts


# --- MEA-005: ingredient-to-product explanation ----------------------------------------------------


def test_proposal_request_links_to_the_plan_revision_that_explains_every_line(
    tmp_path, actor, service, meal_products
):
    versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    prepared = service.prepare_order(actor, request_for(plan))
    request = prepared["request"]
    assert request["recipe_plan_id"] == plan["recipe_plan_id"]
    assert request["recipe_plan_revision"] == plan["recipe_plan_revision"] == 4
    explanation = plan_revisions(request["recipe_plan_id"])[request["recipe_plan_revision"]]
    by_product = {i["product_id"]: i["ingredient_id"] for i in explanation["ingredients"]}
    assert by_product == {
        "recipe-spaghetti": "spaghetti",
        "recipe-egg": "egg",
        "recipe-pepper": "pepper",
    }
    assert {line["product_id"] for line in prepared["snapshot"]["lines"]} == set(by_product)
    assert all(
        i["status"] == "matched" and i["product_fingerprint"] for i in explanation["ingredients"]
    )


def test_every_plan_revision_is_kept_and_shows_the_selection_history(
    tmp_path, actor, meal_products
):
    versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    revisions = plan_revisions(plan["recipe_plan_id"])
    assert sorted(revisions) == [1, 2, 3, 4]
    chosen = [[i["product_id"] for i in revisions[r]["ingredients"]] for r in sorted(revisions)]
    assert chosen == [
        [None, None, None],
        ["recipe-spaghetti", None, None],
        ["recipe-spaghetti", "recipe-egg", None],
        ["recipe-spaghetti", "recipe-egg", "recipe-pepper"],
    ]


def test_request_line_for_a_shared_product_carries_no_ingredient_breakdown(
    tmp_path, actor, service, meal_products
):
    """The request line stays a plain product total; the breakdown is on the snapshot line
    (see the MEA-005 test below) and the saved plan revision keeps the by-reference trace."""
    plan = shared_product_plan(tmp_path, actor, meal_products)
    line = {"product_id": "recipe-spaghetti", "amount": "30", "unit": "KG"}
    prepared = service.prepare_order(actor, request_for(plan, lines=[line]))
    assert not [k for k in prepared["request"]["lines"][0] if "ingredient" in k]
    assert "contributions" not in prepared["request"]["lines"][0]
    explanation = plan_revisions(plan["recipe_plan_id"])[
        prepared["request"]["recipe_plan_revision"]
    ]
    assert [i["ingredient_id"] for i in explanation["ingredients"] if i["product_id"]] == [
        "spaghetti",
        "spaghetti2",
    ]


def test_snapshot_line_names_the_ingredients_it_serves(tmp_path, actor, service, meal_products):
    """MEA-005 stricter reading: the snapshot line names its ingredients and their quantities."""
    plan = shared_product_plan(tmp_path, actor, meal_products)
    line = {"product_id": "recipe-spaghetti", "amount": "30", "unit": "KG"}
    prepared = service.prepare_order(actor, request_for(plan, lines=[line]))
    contributions = prepared["snapshot"]["lines"][0]["contributions"]
    assert [(c["ingredient_id"], c["amount"], c["unit"]) for c in contributions] == [
        ("spaghetti", "20", "KG"),
        ("spaghetti2", "10", "KG"),
    ]


def test_gap_rejected_product_selection_is_recorded(tmp_path, actor, meal_products):
    versions = import_fixture(tmp_path)
    plan = scale_recipe(actor, ref(versions))
    after = match(actor, plan, "spaghetti", "recipe-egg")  # wrong product, refused
    assert after["ingredients"][0]["status"] == "unresolved"
    revision = plan_revisions(plan["recipe_plan_id"])[after["recipe_plan_revision"]]
    assert "recipe-egg" in json.dumps(revision["ingredients"][0])


# --- MEA-006: no count-to-weight invention ---------------------------------------------------------


def product_with_weight():
    p = deepcopy(fixtures.fixture_facts()[0])
    p.update(
        sales_unit="ST",
        base_unit="ST",
        units={"ST": "1"},
        order_step=".01",
        variable_weight=False,
        measures={
            "KG": {"status": "known", "value": "1", "basis": ["authored.structured.weight"]},
            "L": {"status": "unknown", "value": None, "basis": []},
        },
    )
    return p


def test_catalog_quantity_does_not_turn_pieces_into_weight_without_count_evidence():
    p = product_with_weight()  # the product has a KNOWN 1 kg net weight, and still:
    q = quantity(p, Decimal("100"), "piece", True)
    assert q["sales_quantity"] is None and q["proposed_amount"] is None and q["status"] == "unknown"
    evidence = {"piece_per_sales": Decimal("30"), "source": "Authored reviewed evidence"}
    q = quantity(p, Decimal("100"), "piece", True, count_evidence=evidence)
    assert (q["sales_quantity"], q["excess"], q["status"]) == ("4", "20", "derived")
    assert "reviewed_ingredient_count_per_sales_unit" in q["basis"]
    # Count evidence is only consulted for pieces; it never converts a mass or volume.
    q = quantity(p, Decimal("2"), "KG", True, count_evidence=evidence)
    assert "reviewed_ingredient_count_per_sales_unit" not in q["basis"]


def test_piece_ingredient_without_reviewed_count_stays_unresolved_and_blocks_preparation(
    tmp_path, actor, service, meal_products
):
    remove_egg_count()
    versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    egg = plan["ingredients"][1]
    assert (egg["amount"], egg["unit"], egg["status"]) == ("100", "piece", "unresolved")
    assert egg["reason"] == "Verified ingredient count per sales unit is missing."
    assert egg["product_id"] is None and egg["conversion"] is None  # no weight invented
    before = proposal_count()
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, request_for(plan))
    assert error.value.code == "INCOMPLETE_MEAL_PLAN" and proposal_count() == before


def test_reviewed_correction_of_a_count_to_a_weight_is_accepted_only_through_import_review(
    tmp_path, actor, meal_products
):
    """The only 'explicit correction' that exists: an operator review overriding unit/quantity."""
    versions = import_fixture(
        tmp_path, overrides={"egg": {"unit": "g", "quantity": 60, "note": "reviewed: 60 g per egg"}}
    )
    plan = scale_recipe(actor, ref(versions))
    egg = plan["ingredients"][1]
    assert (egg["amount"], egg["unit"]) == ("6", "KG")  # 60 g x 200 / 2


# --- MEA-007: matched or unresolved ----------------------------------------------------------------


def test_unmatched_plan_reports_every_ingredient_unresolved_with_a_reason():
    plan = scaled_plan(make_recipe([(200, "g", "linear"), (1, "tbsp", "damped")]), 200)
    assert [i.status for i in plan.ingredients] == ["unresolved", "unresolved"]
    assert all(i.reason for i in plan.ingredients)


def assert_each_ingredient_is_matched_or_unresolved(plan):
    for item in plan["ingredients"]:
        assert item["status"] in {"matched", "unresolved"}  # never the free-form 'proposed'
        if item["status"] == "matched":
            assert item["reason"] is None and item["product_id"] and item["conversion"]
            assert item["conversion"]["sales_quantity"]
        else:
            assert item["reason"] and not item["product_id"] and item["conversion"] is None


def test_saved_plan_ingredients_are_always_matched_or_unresolved(tmp_path, actor, meal_products):
    versions = import_fixture(tmp_path)
    scaled = scale_recipe(actor, ref(versions))
    assert_each_ingredient_is_matched_or_unresolved(scaled)
    full = match_all(actor, scaled)
    assert [i["status"] for i in full["ingredients"]] == ["matched"] * 3
    assert_each_ingredient_is_matched_or_unresolved(full)

    remove_egg_count()
    actor2 = actor | {"_turn_id": str(uuid4())}
    partial = match_all(actor2, scale_recipe(actor2, ref(versions)))
    assert [i["status"] for i in partial["ingredients"]] == ["matched", "unresolved", "matched"]
    assert_each_ingredient_is_matched_or_unresolved(partial)

    actor3 = actor | {"_turn_id": str(uuid4())}
    wrong = match(actor3, scale_recipe(actor3, ref(versions)), "spaghetti", "recipe-egg")
    assert_each_ingredient_is_matched_or_unresolved(wrong)
    assert wrong["ingredients"][0]["reason"].startswith("No current reviewed evidence")


def test_unreviewed_form_leaves_everything_unresolved_with_the_form_reason(
    tmp_path, actor, meal_products
):
    versions = import_fixture(tmp_path, review=False)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    assert [i["status"] for i in plan["ingredients"]] == ["unresolved"] * 3
    assert {i["reason"] for i in plan["ingredients"]} == {
        "Review the required ingredient form before product matching."
    }


# --- MEA-008: a basket is not complete while an ingredient is unresolved ---------------------------


def test_prepare_is_refused_while_any_ingredient_is_unresolved(
    tmp_path, actor, service, meal_products
):
    remove_egg_count()
    versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    assert [i["status"] for i in plan["ingredients"]] == ["matched", "unresolved", "matched"]
    before = proposal_count()
    complete_looking = [  # a basket that covers all three ingredients' products anyway
        {"product_id": "recipe-spaghetti", "amount": "20", "unit": "KG"},
        {"product_id": "recipe-egg", "amount": "100", "unit": "piece"},
        {"product_id": "recipe-pepper", "amount": "0.2", "unit": "KG"},
    ]
    for lines in (None, complete_looking):  # only matched lines, then all three
        with pytest.raises(Problem) as error:
            service.prepare_order(actor, request_for(plan, lines=lines))
        assert error.value.code == "INCOMPLETE_MEAL_PLAN"
    assert proposal_count() == before
    with connection() as c:
        locked = c.execute(
            "SELECT locked,proposal_id FROM recipe_plans WHERE id=%s", (plan["recipe_plan_id"],)
        ).fetchone()
    assert not locked["locked"] and locked["proposal_id"] is None


def test_agent_tool_refuses_prepare_while_the_saved_plan_is_unresolved(
    tmp_path, actor, service, meal_products
):
    versions = import_fixture(tmp_path)
    session = ToolSession(actor, service)
    session.invoke("scale_recipe", json.dumps(dict(versions[0], portions=200)))
    request = request_for(
        scale_recipe(actor, ref(versions)),
        lines=[{"product_id": "recipe-spaghetti", "amount": "20", "unit": "KG"}],
    ).model_dump(mode="json")
    request.pop("idempotency_key")
    with pytest.raises(Problem) as error:
        session.invoke("prepare_order", json.dumps(request))
    assert error.value.code == "INCOMPLETE_MEAL_PLAN"


def free_form_session(tmp_path, actor, service):
    """Earlier turn leaves an unresolved saved plan; a later turn sends a one-ingredient plan."""
    versions = import_fixture(tmp_path, review=False)
    unresolved = scale_recipe(actor, ref(versions))
    assert all(i["status"] == "unresolved" for i in unresolved["ingredients"])
    later = ToolSession(actor | {"_turn_id": str(uuid4())}, service)
    later.invoke("get_product", json.dumps({"product_id": "recipe-spaghetti"}))
    later.invoke(
        "publish_meal_plan",
        json.dumps(
            {
                "title": unresolved["title"],
                "portions": 200,
                "ingredients": [
                    {
                        "name": "Spaghetti",
                        "amount": "20",
                        "unit": "KG",
                        "product_id": "recipe-spaghetti",
                    }
                ],
            }
        ),
    )
    request = {
        "request_id": "Free-form basket",
        "destination": "hotel-helsinki",
        "delivery_date": str(date.today() + timedelta(days=2)),
        "budget_gross": "1000",
        "lines": [{"product_id": "recipe-spaghetti", "amount": "20", "unit": "KG"}],
    }
    return later, request


def test_free_form_basket_that_omits_ingredients_is_prepared_but_labelled_free_form(
    tmp_path, actor, service, meal_products
):
    """Characterisation of the documented cross-turn limit (docs/recipes.md)."""
    later, request = free_form_session(tmp_path, actor, service)
    result = later.invoke("prepare_order", json.dumps(request))
    assert result["recipe_basis"] == "free_form" and result["request"]["recipe_plan_id"] is None


@pytest.mark.xfail(
    strict=True,
    reason="MEA-008 gap: a later-turn free-form plan that names the same dish as an earlier "
    "unresolved saved plan is prepared (only labelled free_form); proposed contract: refuse it. "
    "Backend half exists (aimo.recipe_guard, Service.ensure_saved_plan_resolved); remaining step: "
    "ToolSession.prepare (agent_tools.py, person 2) must call it. See evidence MEA-008-requests.md.",
)
def test_gap_free_form_basket_for_a_dish_with_unresolved_saved_plan_is_refused(
    tmp_path, actor, service, meal_products
):
    later, request = free_form_session(tmp_path, actor, service)
    with pytest.raises(Problem):
        later.invoke("prepare_order", json.dumps(request))


# --- MEA-009: required amount versus pack-rounded purchase -----------------------------------------


def test_required_amount_stays_separate_from_the_pack_rounded_purchase(
    tmp_path, actor, service, meal_products
):
    versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    pasta, eggs, pepper = plan["ingredients"]
    expected = [
        (pasta, "20", "21", "7", "1"),
        (eggs, "100", "120", "4", "20"),
        (pepper, "0.2", "0.21", "1", "0.01"),
    ]
    for item, required, bought, packs, excess in expected:
        c = item["conversion"]
        assert item["amount"] == required != c["proposed_amount"] == bought
        assert (c["requested_amount"], c["sales_quantity"], c["excess"]) == (
            required,
            packs,
            excess,
        )
        assert Decimal(c["proposed_amount"]) - Decimal(required) == Decimal(excess)
    prepared = service.prepare_order(actor, request_for(plan))
    for line in prepared["snapshot"]["lines"]:
        q = line["quantity"]
        assert Decimal(q["proposed_amount"]) > Decimal(q["requested_amount"])
    assert prepared["request"]["lines"][0]["amount"] == "20"  # request keeps the required amount


def test_purchase_amount_field_is_a_copy_of_the_required_amount_not_the_rounded_purchase(
    tmp_path, actor, meal_products
):
    """Characterisation of a naming trap: purchase_amount == amount; rounding is in conversion."""
    versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    for item in plan["ingredients"]:
        assert item["purchase_amount"] == item["amount"]
        assert item["purchase_unit"] == item["unit"]
        assert item["purchase_amount"] != item["conversion"]["proposed_amount"]


def test_ingredient_purchased_amounts_add_up_to_the_basket_line(
    tmp_path, actor, service, meal_products
):
    """MEA-009 stricter reading, measured on the proposal the customer sees: the purchased
    amounts per ingredient on the snapshot line add up to the line (a shared pack is split).

    The saved plan still shows each ingredient converted ALONE (7 + 4 packs there against 10
    packs bought), which is why the split is made on the proposal, not read from the plan."""
    plan = shared_product_plan(tmp_path, actor, meal_products)
    line = {"product_id": "recipe-spaghetti", "amount": "30", "unit": "KG"}
    prepared = service.prepare_order(actor, request_for(plan, lines=[line]))
    snapshot_line = prepared["snapshot"]["lines"][0]
    bought = Fraction(snapshot_line["quantity"]["proposed_amount"])
    assert bought == 30
    shares = [Fraction(c["purchased_amount"]) for c in snapshot_line["contributions"]]
    assert len(shares) == 2 and sum(shares) == bought
