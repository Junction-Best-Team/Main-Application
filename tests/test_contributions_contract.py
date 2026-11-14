"""MEA-005 / MEA-009 / BAS-002 stricter readings: ingredient contributions on a basket line.

Owner decisions: a proposal (snapshot) line names the ingredient(s) it serves with their
contributing quantities; rejected product selections are recorded; the per-ingredient purchased
amounts add up to the basket line (a shared pack is split across the ingredients, never converted
alone per ingredient). Authored fixtures only; no live supplier call.
"""

import json
from copy import deepcopy
from fractions import Fraction
from uuid import uuid4

import pytest
import test_recipe_arithmetic as arithmetic
from pydantic import ValidationError
from test_recipe_arithmetic import (
    import_fixture,
    match,
    match_all,
    plan_revisions,
    ref,
    request_for,
    source_recipe,
    write,
)

from aimo.basket import allocate_line, line_contributions
from aimo.chat_schemas import MealPlan
from aimo.db import fingerprint
from aimo.purchases import material_fingerprint
from aimo.recipe_batch import IngredientMatch, MatchIngredients, match_ingredients
from aimo.recipe_import import import_product_evidence
from aimo.recipes import scale_recipe
from aimo.schemas import LineRequest, PrepareRequest

# Fixtures defined in test_recipe_arithmetic (authored recipe and product fixtures).
actor = arithmetic.actor
clean_recipes = arithmetic.clean_recipes
meal_products = arithmetic.meal_products


def quantity(requested="30.5", unit="KG", proposed="33", sales="11", excess="2.5"):
    return dict(
        requested_amount=requested,
        requested_unit=unit,
        sales_unit="ST",
        sales_quantity=sales,
        proposed_amount=proposed,
        excess=excess,
    )


def contribution(name, amount, unit="KG", ingredient_id=None):
    return dict(ingredient=name, ingredient_id=ingredient_id, amount=amount, unit=unit)


def total(shares, key):
    return sum(Fraction(s[key]) for s in shares)


# --- pure allocation ------------------------------------------------------------------------


def test_shares_sum_exactly_to_the_line_for_terminating_decimals():
    q = quantity()
    shares = allocate_line(q, [contribution("a", "20"), contribution("b", "10.5")])
    assert total(shares, "purchased_amount") == Fraction("33")
    assert total(shares, "excess") == Fraction("2.5")
    assert total(shares, "sales_quantity") == Fraction("11")
    assert [(s["ingredient"], s["amount"]) for s in shares] == [("a", "20"), ("b", "10.5")]


def test_three_ingredients_on_one_product_with_non_terminating_shares_sum_exactly():
    q = quantity(requested="21", proposed="30", sales="10", excess="9")
    shares = allocate_line(
        q, [contribution("a", "7"), contribution("b", "7"), contribution("c", "7")]
    )
    assert [s["purchased_amount"] for s in shares] == ["10", "10", "10"]
    q = quantity(requested="10", proposed="10", sales="10", excess="0")
    shares = allocate_line(q, [contribution(n, "1") for n in "abc"])
    assert {s["purchased_amount"] for s in shares} == {"10/3"}  # exact fraction, not rounded
    assert total(shares, "purchased_amount") == Fraction(10)
    assert total(shares, "excess") == 0


def test_an_unequal_three_way_split_is_proportional_and_exact():
    q = quantity(requested="37", proposed="39", sales="13", excess="2")
    shares = allocate_line(
        q, [contribution("a", "20"), contribution("b", "10"), contribution("c", "7")]
    )
    assert [Fraction(s["purchased_amount"]) for s in shares] == [
        Fraction(39 * 20, 37),
        Fraction(39 * 10, 37),
        Fraction(39 * 7, 37),
    ]
    assert total(shares, "purchased_amount") == Fraction(39)
    assert total(shares, "excess") == Fraction(2)


def test_each_share_covers_its_own_need():
    q = quantity(requested="37", proposed="39", sales="13", excess="2")
    shares = allocate_line(q, [contribution("a", "20"), contribution("b", "17")])
    for s in shares:
        assert Fraction(s["purchased_amount"]) >= Fraction(s["amount"])
        assert Fraction(s["purchased_amount"]) - Fraction(s["amount"]) == Fraction(s["excess"])


def test_no_purchased_share_when_the_line_amount_is_unknown_or_units_differ():
    unknown = quantity(proposed=None, sales=None, excess=None)
    shares = allocate_line(unknown, [contribution("a", "5", "KG")])
    assert shares == [
        dict(ingredient="a", ingredient_id=None, amount="5", unit="KG"),
    ]
    other_unit = allocate_line(quantity(), [contribution("a", "5", "L")])
    assert "purchased_amount" not in other_unit[0]


def test_allocation_does_not_mutate_its_inputs():
    q, parts = quantity(), [contribution("a", "20"), contribution("b", "10.5")]
    before = deepcopy((q, parts))
    allocate_line(q, parts)
    assert (q, parts) == before


# --- request model: free-form contributions ---------------------------------------------------


def test_request_dump_is_unchanged_when_there_are_no_contributions():
    line = LineRequest(product_id="p", amount="5", unit="L")
    assert "contributions" not in line.model_dump(mode="json")
    assert "contributions" not in line.model_dump()
    line = LineRequest(
        product_id="p", amount="5", unit="L", contributions=[contribution("a", "5", "L")]
    )
    assert line.model_dump(mode="json")["contributions"][0]["ingredient"] == "a"


def test_contributions_must_add_up_to_the_line_amount_in_the_same_unit():
    parts = [contribution("a", "5", "L"), contribution("b", "5.5", "L")]
    LineRequest(product_id="p", amount="10.5", unit="L", contributions=parts)
    with pytest.raises(ValidationError, match="add up"):
        LineRequest(product_id="p", amount="10", unit="L", contributions=parts)


def test_contributions_are_not_accepted_on_a_saved_recipe_request(request_data):
    request_data.pop("idempotency_key", None)
    request_data["recipe_plan_id"] = str(uuid4())
    request_data["recipe_plan_revision"] = 1
    request_data["lines"][0]["contributions"] = [
        contribution("a", str(request_data["lines"][0]["amount"]), request_data["lines"][0]["unit"])
    ]
    with pytest.raises(ValidationError, match="saved recipe"):
        PrepareRequest(**request_data, idempotency_key="12345678")


def test_free_form_contributions_reach_the_snapshot_line_with_exact_shares(
    agent, service, request_data
):
    request_data.update(idempotency_key=str(uuid4()), requirements={})
    request_data["lines"] = [
        {
            "product_id": "464306",
            "amount": "10.5",
            "unit": "L",
            "contributions": [
                contribution("cream sauce", "5", "L"),
                contribution("soup", "5.5", "L"),
            ],
        }
    ]
    prepared = service.prepare_order(agent, PrepareRequest(**request_data))
    line = prepared["snapshot"]["lines"][0]
    assert [(c["ingredient"], c["amount"], c["unit"]) for c in line["contributions"]] == [
        ("cream sauce", "5", "L"),
        ("soup", "5.5", "L"),
    ]
    assert total(line["contributions"], "purchased_amount") == Fraction(
        line["quantity"]["proposed_amount"]
    )
    assert total(line["contributions"], "sales_quantity") == Fraction(
        line["quantity"]["sales_quantity"]
    )
    assert prepared["request"]["lines"][0]["contributions"][0]["ingredient"] == "cream sauce"


def test_a_line_without_contributions_has_none_on_the_snapshot(agent, service, request_data):
    request_data.update(idempotency_key=str(uuid4()), requirements={})
    prepared = service.prepare_order(agent, PrepareRequest(**request_data))
    assert prepared["snapshot"]["lines"][0].get("contributions") is None
    assert "contributions" not in prepared["request"]["lines"][0]


# --- saved recipe path ----------------------------------------------------------------------


def three_on_one_product(tmp_path, actor, products):
    """Three ingredients (20, 10 and 7 KG of spaghetti) matched to ONE 3 kg product."""
    raw = source_recipe()
    extra = lambda iid, grams: dict(  # noqa: E731
        id=iid, name={"en": iid}, quantity=grams, unit="g", scaling="linear"
    )
    raw["ingredients"] = [raw["ingredients"][0], extra("spaghetti2", 100), extra("spaghetti3", 70)]
    rows = [
        dict(
            product_id="recipe-spaghetti",
            product_fingerprint=fingerprint(products[0]),
            ingredient_id=iid,
            form="dry",
            source="Authored reviewed product evidence",
            piece_per_sales=None,
        )
        for iid in ("spaghetti2", "spaghetti3")
    ]
    path = tmp_path / "extra-evidence.json"
    write(path, rows)
    import_product_evidence(path)
    plan = scale_recipe(actor, ref(import_fixture(tmp_path, [raw])))
    for iid in ("spaghetti", "spaghetti2", "spaghetti3"):
        plan = match(actor, plan, iid, "recipe-spaghetti")
    return plan


def test_shared_product_line_names_each_ingredient_with_its_share(
    tmp_path, actor, service, meal_products
):
    plan = three_on_one_product(tmp_path, actor, meal_products)
    line = {"product_id": "recipe-spaghetti", "amount": "37", "unit": "KG"}
    prepared = service.prepare_order(actor, request_for(plan, lines=[line]))
    snapshot_line = prepared["snapshot"]["lines"][0]
    shares = snapshot_line["contributions"]
    assert [(c["ingredient_id"], c["amount"]) for c in shares] == [
        ("spaghetti", "20"),
        ("spaghetti2", "10"),
        ("spaghetti3", "7"),
    ]
    q = snapshot_line["quantity"]
    assert (q["proposed_amount"], q["sales_quantity"]) == ("39", "13")
    assert total(shares, "purchased_amount") == Fraction(39)
    assert total(shares, "excess") == Fraction(2)
    assert total(shares, "sales_quantity") == Fraction(13)
    assert Fraction(shares[0]["purchased_amount"]) == Fraction(39 * 20, 37)


def test_each_line_names_only_the_ingredients_it_serves(tmp_path, actor, service, meal_products):
    plan = match_all(actor, scale_recipe(actor, ref(import_fixture(tmp_path))))
    prepared = service.prepare_order(actor, request_for(plan))
    served = {
        line["product_id"]: [c["ingredient_id"] for c in line["contributions"]]
        for line in prepared["snapshot"]["lines"]
    }
    assert served == {
        "recipe-spaghetti": ["spaghetti"],
        "recipe-egg": ["egg"],
        "recipe-pepper": ["pepper"],
    }
    for line in prepared["snapshot"]["lines"]:  # a sole ingredient takes the whole line
        (only,) = line["contributions"]
        assert only["purchased_amount"] == line["quantity"]["proposed_amount"]


def test_line_contributions_ignores_plan_ingredients_that_are_not_on_the_basket():
    plan = {
        "ingredients": [
            dict(
                ingredient_id="a",
                name="A",
                product_id="p1",
                purchase_amount="2",
                purchase_unit="KG",
            ),
            dict(
                ingredient_id="b",
                name="B",
                product_id="p2",
                purchase_amount="3",
                purchase_unit="KG",
            ),
            dict(
                ingredient_id="c",
                name="C",
                product_id=None,
                purchase_amount=None,
                purchase_unit=None,
            ),
        ]
    }
    request = PrepareRequest(
        idempotency_key="12345678",
        request_id="r",
        destination="d",
        delivery_date="2030-01-01",
        lines=[{"product_id": "p1", "amount": "2", "unit": "KG"}],
    )
    got = line_contributions(request, plan)
    assert list(got) == ["p1"] and got["p1"][0]["ingredient_id"] == "a"
    assert line_contributions(request, None) == {}


def test_material_fingerprint_is_unchanged_by_contributions(
    tmp_path, actor, service, meal_products
):
    plan = three_on_one_product(tmp_path, actor, meal_products)
    line = {"product_id": "recipe-spaghetti", "amount": "37", "unit": "KG"}
    prepared = service.prepare_order(actor, request_for(plan, lines=[line]))
    snapshot, request = prepared["snapshot"], prepared["request"]
    assert snapshot["lines"][0]["contributions"]
    with_contributions = material_fingerprint(request, snapshot, 1)
    stripped = deepcopy(snapshot)
    for item in stripped["lines"]:
        item.pop("contributions")
    assert material_fingerprint(request, stripped, 1) == with_contributions
    for item in snapshot["lines"]:  # different shares do not change it either
        item["contributions"][0]["purchased_amount"] = "0"
    assert material_fingerprint(request, snapshot, 1) == with_contributions


# --- rejected selections on the batch path -----------------------------------------------------


def batch(actor, plan, *pairs):
    return match_ingredients(
        actor,
        MatchIngredients(
            plan_id=plan["recipe_plan_id"],
            revision=plan["recipe_plan_revision"],
            matches=[IngredientMatch(ingredient_id=i, product_id=p) for i, p in pairs],
        ),
    )


def test_batch_records_a_rejected_product_selection_and_keeps_it(tmp_path, actor, meal_products):
    plan = scale_recipe(actor, ref(import_fixture(tmp_path)))
    after = batch(actor, plan, ("spaghetti", "recipe-egg"), ("egg", "recipe-egg"))
    assert after["ingredients"][0]["status"] == "unresolved"
    stored = plan_revisions(plan["recipe_plan_id"])[after["recipe_plan_revision"]]
    spaghetti, egg = stored["ingredients"][0], stored["ingredients"][1]
    assert spaghetti["rejected"] == [{"product_id": "recipe-egg", "reason": spaghetti["reason"]}]
    assert not egg.get("rejected")  # a matched ingredient has nothing rejected

    again = batch(actor, after, ("spaghetti", "recipe-pepper"))  # second wrong product: appended
    assert [r["product_id"] for r in again["ingredients"][0]["rejected"]] == [
        "recipe-egg",
        "recipe-pepper",
    ]
    final = batch(actor, again, ("spaghetti", "recipe-spaghetti"))  # matched: history stays
    item = final["ingredients"][0]
    assert item["status"] == "matched" and item["product_id"] == "recipe-spaghetti"
    assert [r["product_id"] for r in item["rejected"]] == ["recipe-egg", "recipe-pepper"]
    old = plan_revisions(plan["recipe_plan_id"])[after["recipe_plan_revision"]]
    assert [r["product_id"] for r in old["ingredients"][0]["rejected"]] == ["recipe-egg"]


def test_batch_without_a_rejection_records_none(tmp_path, actor, meal_products):
    plan = scale_recipe(actor, ref(import_fixture(tmp_path)))
    after = batch(actor, plan, ("spaghetti", "recipe-spaghetti"))
    assert not any(item.get("rejected") for item in after["ingredients"])


def test_gap_meal_plan_accepts_a_rejected_selection_on_an_ingredient(
    tmp_path, actor, meal_products
):
    plan = scale_recipe(actor, ref(import_fixture(tmp_path)))
    after = batch(actor, plan, ("spaghetti", "recipe-egg"))
    assert json.dumps(after).count("recipe-egg") == 1
    MealPlan.model_validate(after)
