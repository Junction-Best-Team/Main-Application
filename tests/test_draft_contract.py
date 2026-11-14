"""Strict-xfail tests for Draft requirements whose behaviour does not exist yet.

Covers JNP3-MEA-011, MEA-012, MEA-013, SUP-007, BAS-008, BAS-009 and the known PRP-006 line bug.
Each test asserts the DESIRED behaviour and is marked `xfail(strict=True)`: it stays quiet while
the feature is missing and turns red (XPASS) the moment someone implements it, which is the
signal to remove the marker. Field names marked "pending" in the requirements are assumptions.

All data is authored (`aimo.fixtures`, `FixtureClient`, in-test dictionaries) and the supplier
transport is a stub: no network, no live key. BAS-006, BAS-007 and the PRP-006 total are covered
in `test_arithmetic_contract.py` and deliberately not repeated here.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from aimo.chat_schemas import Ingredient, MealPlan
from aimo.db import Problem
from aimo.recipe_schemas import Recipe
from aimo.recipes import scaled_plan
from aimo.schemas import LookupRequest, PrepareRequest, PurchaseRequest
from aimo.service import Service
from aimo.upstream import FixtureClient, ValioClient


def recipe(count=1, quantity=100, unit="g", base_servings=1):
    """Authored recipe with `count` identical linear ingredients."""
    return Recipe.model_validate(
        dict(
            id="authored-recipe",
            title="Authored recipe",
            summary="",
            base_servings=base_servings,
            category="authored",
            instructions=[],
            ingredients=[
                dict(
                    id=f"i{n}",
                    name=f"ingredient {n}",
                    quantity=quantity,
                    unit=unit,
                    form="raw",
                    scaling="linear",
                )
                for n in range(count)
            ],
        )
    )


def line(product_id, amount="1", unit="KG"):
    return {"product_id": product_id, "amount": amount, "unit": unit}


def purchase(lines):
    return {
        "request_id": "draft-contract",
        "destination": "hotel-helsinki",
        "delivery_date": "2030-01-01",
        "lines": lines,
    }


# --- MEA-011: a configured maximum quantity per portion --------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="MEA-011 Draft: scaled_plan has no maximum quantity per portion (value pending)",
)
def test_absurd_quantity_per_portion_is_rejected():
    # 9,999,999 kg per serving x 10,000 portions = 99,999,990,000 kg is accepted today.
    with pytest.raises(Problem):
        scaled_plan(recipe(quantity=9999999, unit="kg"), 10000)


# --- MEA-012: round a scaled quantity UP to four decimal places ------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="MEA-012 Draft: a quantity needing more than 4 decimals is left unresolved, not rounded up",
)
@pytest.mark.parametrize(
    "grams,base_servings,portions,expected",
    [
        (100, 6, 200, "3.3334"),  # 3.33333... kg
        (200, 6, 200, "6.6667"),  # 6.66666... kg
        (100, 3, 1, "0.0334"),  # 0.033333... kg: half-up would give 0.0333, so this must be ceil
    ],
)
def test_scaled_quantity_is_rounded_up_to_four_decimals(grams, base_servings, portions, expected):
    plan = scaled_plan(recipe(quantity=grams, base_servings=base_servings), portions)
    assert plan.ingredients[0].amount == expected
    assert plan.ingredients[0].unit == "KG"


def test_exactly_terminating_scaled_quantity_stays_unchanged():
    # Regression guard that passes today and must keep passing once MEA-012 rounds up:
    # 150 g x 200 / 6 = 5 kg exactly, so no rounding may touch it.
    plan = scaled_plan(recipe(quantity=150, base_servings=6), 200)
    assert plan.ingredients[0].amount == "5"


# --- MEA-013: meal plans and purchase requests of up to 1000 ingredients ---------------------

BIG = 1000


@pytest.mark.xfail(
    strict=True, reason="MEA-013 Draft: MealPlan.ingredients is capped at 30, not 1000"
)
def test_meal_plan_accepts_one_thousand_ingredients():
    ingredients = [Ingredient(name=f"ingredient {n}", amount="1", unit="KG") for n in range(BIG)]
    assert len(MealPlan(title="Big", portions=1, ingredients=ingredients).ingredients) == BIG


@pytest.mark.xfail(
    strict=True, reason="MEA-013 Draft: PurchaseRequest.lines is capped at 30, not 1000"
)
def test_purchase_request_accepts_one_thousand_lines():
    lines = [line(f"authored-{n}") for n in range(BIG)]
    assert len(PurchaseRequest.model_validate(purchase(lines)).lines) == BIG


@pytest.mark.xfail(
    strict=True,
    reason="MEA-013 Draft: Recipe is capped at 100 ingredients and scaled_plan at 30, not 1000",
)
def test_recipe_with_one_thousand_ingredients_can_be_scaled():
    plan = scaled_plan(recipe(count=BIG), 2)
    assert len(plan.ingredients) == BIG


@pytest.mark.xfail(
    strict=True, reason="MEA-013 Draft: LookupRequest.product_ids is capped at 50, not 1000"
)
def test_lookup_request_accepts_one_thousand_product_ids():
    request = LookupRequest(
        product_ids=[f"authored-{n}" for n in range(BIG)], delivery_date=date(2030, 1, 1)
    )
    assert len(request.product_ids) == BIG


# --- SUP-007: split price/availability lookups into batches of at most 1000 ------------------

SUPPLIER_LIMIT = 1000


@pytest.mark.xfail(
    strict=True,
    reason="SUP-007 Draft: ValioClient.lookup sends every product id in one request per endpoint",
)
def test_lookup_is_split_into_batches_within_the_supplier_limit():
    ids = [f"authored-{n}" for n in range(2500)]
    sent = []

    def stub_post(endpoint, payload):
        # Stand-in for the supplier: records each body and echoes one row per requested product.
        sent.append((endpoint, list(payload["products"])))
        return {"products": [{"productId": pid} for pid in payload["products"]]}

    client = ValioClient()
    client.post = stub_post  # no network and no key are ever used
    result = client.lookup("authored-customer", ids, date(2030, 1, 1))

    assert sent, "lookup made no request"
    assert all(len(products) <= SUPPLIER_LIMIT for _, products in sent)
    for envelope in ("price", "availability"):
        returned = [row["productId"] for row in result[envelope]["products"]]
        assert sorted(returned) == sorted(ids), f"{envelope} lost or repeated ids"


# --- BAS-008: numeric shortfall per basket line ----------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="BAS-008 Draft: a short line carries only the INSUFFICIENT_STOCK text, no numeric shortfall",
)
def test_line_reports_numeric_shortfall_when_stock_is_below_the_need(agent, request_data):
    client = FixtureClient()
    client.stock["464306"] = "3"
    request_data["lines"] = [line("464306", "10", "L")]
    request_data["idempotency_key"] = str(uuid4())
    proposal = Service(client).prepare_order(agent, PrepareRequest(**request_data))
    snapshot = proposal["snapshot"]
    assert "INSUFFICIENT_STOCK" in {r["code"] for r in snapshot["reasons"]}  # the text exists today
    quantity = snapshot["lines"][0]["quantity"]
    expected = Decimal(quantity["sales_quantity"]) - 3  # need in sales units minus available
    assert expected > 0
    # The field name is pending; `shortfall` (decimal string, in sales units) is the assumption.
    assert quantity.get("shortfall") is not None, "line has no numeric shortfall field"
    assert Decimal(quantity["shortfall"]) == expected


# --- BAS-009: one unit per product by configured priority (kg, then L, then pieces) ----------


class CapturedPrepare(Exception):
    """Raised by the fake service once it has seen the request, to stop before any proposal."""


class RecordingService:
    """Minimal authored stand-in for Service: serves a product and records the prepare call."""

    def __init__(self):
        self.prepared = None

    def get_product(self, identity, product_id):
        from copy import deepcopy

        from aimo.fixtures import fixture_facts

        result = deepcopy(fixture_facts()[0])
        result.update(id=product_id, name=product_id, sales_unit="KG", base_unit="KG")
        result.update(units={"KG": "1", "ST": "0.25"})
        result["provenance"]["product_id"] = product_id
        return result

    def prepare_order(self, identity, request):
        self.prepared = request
        raise CapturedPrepare


@pytest.mark.xfail(
    strict=True,
    reason="BAS-009 Draft: the same product in two units is rejected, not combined into one KG line",
)
def test_product_requested_in_two_units_becomes_one_line_in_the_priority_unit():
    # Layer chosen: ToolSession.prepare with a recording fake service (pattern of test_agent.py).
    # It is the simplest layer without network that sees both the plan keyed on (product, unit)
    # and the PurchaseRequest.unique_lines rule that make this basket impossible today.
    import json

    from aimo.agent_tools import ToolSession

    identity = {
        "id": "internal-agent",
        "buyer_id": "hotel",
        "role": "agent",
        "active": True,
        "_turn_id": str(uuid4()),
    }
    service = RecordingService()
    session = ToolSession(identity, service)
    session.invoke("get_product", json.dumps({"product_id": "pasta"}))
    plan = {
        "title": "Pasta",
        "portions": 4,
        "ingredients": [
            {"name": "pasta dry", "amount": "2", "unit": "KG", "product_id": "pasta"},
            {"name": "pasta fresh", "amount": "10", "unit": "ST", "product_id": "pasta"},
        ],
    }
    session.invoke("publish_meal_plan", json.dumps(plan))
    request = purchase([line("pasta", "2", "KG"), line("pasta", "10", "ST")])
    rejected = None
    try:
        session.invoke("prepare_order", json.dumps(request))
    except CapturedPrepare:
        pass
    except Problem as problem:
        rejected = problem.code
    assert service.prepared is not None, f"basket rejected before the service: {rejected}"
    lines = service.prepared.lines
    assert [(entry.product_id, entry.unit) for entry in lines] == [("pasta", "KG")]


# --- PRP-006 line bug: an unpriced deposit must not show as zero on the line -----------------


class DepositWithoutPrice(FixtureClient):
    """Supplier answers for the product but marks the deposit material's price as an error."""

    def lookup(self, customer, ids, delivery_date):
        raw = super().lookup(customer, ids, delivery_date)
        for row in raw["price"]["products"]:
            if row["productId"] == "demo-deposit":
                row["error"] = True
        return raw


@pytest.mark.xfail(
    strict=True,
    reason="PRP-006 Draft: with an unpriced deposit the total is withheld but the line shows gross and deposits 0",
)
def test_line_gross_and_deposits_are_unknown_when_the_deposit_has_no_price(agent, request_data):
    request_data.update(
        requirements={},
        idempotency_key=str(uuid4()),
        lines=[line("460123", "10", "KI")],
    )
    proposal = Service(DepositWithoutPrice()).prepare_order(agent, PrepareRequest(**request_data))
    snapshot = proposal["snapshot"]
    assert snapshot["gross_total"] is None and snapshot["deposits_gross"] is None  # works today
    shown = snapshot["lines"][0]
    assert shown["gross"] is None and shown["deposits_gross"] is None  # unknown, not zero
