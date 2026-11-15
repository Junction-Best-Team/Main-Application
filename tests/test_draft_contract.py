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
from pydantic import ValidationError
from supplier_fixture import FixtureClient

from aimo.chat_schemas import Ingredient, MealPlan
from aimo.db import Problem
from aimo.recipe_schemas import Recipe
from aimo.recipes import scaled_plan
from aimo.schemas import LookupRequest, PrepareRequest, PurchaseRequest
from aimo.service import Service
from aimo.upstream import ValioClient


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


# --- MEA-011 is the 30,000 kg per order limit (tests/test_order_weight.py). The recipe-only
# per-portion bound of PR #133 was removed on the owner's answer to Q-96.


# --- MEA-012: round a scaled quantity UP to four decimal places ------------------------------


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


# --- MEA-013: meal plans and purchase requests of up to 100 ingredients ----------------------
# Owner (Q-67): "raise the limit to 100, not 1000, and apply this everywhere". The supplier lookup
# keeps the supplier's own per-request limit of 1000 product ids (LookupRequest, MAX_MATERIALS).

LIMIT = 100
SUPPLIER_IDS = 1000


def test_meal_plan_accepts_one_hundred_ingredients_and_refuses_one_more():
    ingredients = [Ingredient(name=f"ingredient {n}", amount="1", unit="KG") for n in range(LIMIT)]
    assert len(MealPlan(title="Big", portions=1, ingredients=ingredients).ingredients) == LIMIT
    with pytest.raises(ValidationError):
        MealPlan(
            title="Big",
            portions=1,
            ingredients=ingredients + [Ingredient(name="one more", amount="1", unit="KG")],
        )


def test_purchase_request_accepts_one_hundred_lines_and_refuses_one_more():
    lines = [line(f"authored-{n}") for n in range(LIMIT)]
    assert len(PurchaseRequest.model_validate(purchase(lines)).lines) == LIMIT
    with pytest.raises(ValidationError):
        PurchaseRequest.model_validate(purchase(lines + [line("authored-100")]))


def test_recipe_with_one_hundred_ingredients_can_be_scaled_and_one_more_is_refused():
    full = recipe(count=LIMIT)
    assert len(scaled_plan(full, 2).ingredients) == LIMIT
    with pytest.raises(ValidationError):
        recipe(count=LIMIT + 1)  # the Recipe model itself stops at 100
    # scaled_plan keeps its own guard for a recipe that bypassed validation
    over = full.model_copy(update={"ingredients": full.ingredients + full.ingredients[:1]})
    with pytest.raises(Problem) as error:
        scaled_plan(over, 2)
    assert error.value.code == "RECIPE_TOO_LARGE" and "100" in error.value.message


def test_lookup_request_keeps_the_suppliers_limit_of_one_thousand_product_ids():
    request = LookupRequest(
        product_ids=[f"authored-{n}" for n in range(SUPPLIER_IDS)], delivery_date=date(2030, 1, 1)
    )
    assert len(request.product_ids) == SUPPLIER_IDS
    with pytest.raises(ValidationError):
        LookupRequest(
            product_ids=[f"authored-{n}" for n in range(SUPPLIER_IDS + 1)],
            delivery_date=date(2030, 1, 1),
        )


# --- SUP-007: split price/availability lookups into batches of at most 1000 ------------------

SUPPLIER_LIMIT = 1000


# WS-A implemented the batching (SUP-007), so this is now an ordinary passing test: it XPASSed
# strictly once the two branches were combined and its xfail mark was removed.
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
    # BAS-008 (Approved): `shortfall`, a decimal string in sales units like `sales_quantity`.
    assert quantity.get("shortfall") is not None, "line has no numeric shortfall field"
    assert Decimal(quantity["shortfall"]) == expected


# --- BAS-009: one unit per product by configured priority (kg, then L, then pieces) ----------


class CapturedPrepare(Exception):
    """Raised by the fake service once it has seen the request, to stop before any proposal."""


class RecordingService:
    """Minimal authored stand-in for Service: serves a product and records the prepare call."""

    def __init__(self):
        self.prepared = None

    def ensure_saved_plan_resolved(self, identity, title):
        return None

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
    # Unknown, not zero and not the price without the deposit.
    assert shown["gross"] is None and shown["deposits_gross"] is None
    assert shown["net"] is None and shown["tax"] is None
    assert "DEPOSIT_UNRESOLVED" in {r["code"] for r in snapshot["reasons"]}
    assert proposal["policy_outcome"] == "needs_resolution"


def test_shortfall_is_absent_when_stock_covers_the_need_and_keeps_old_fingerprints(
    agent, request_data
):
    """No `shortfall` key on a covered line: earlier proposals hash the same quantity dict."""
    request_data["lines"] = [line("464306", "10", "L")]
    request_data["idempotency_key"] = str(uuid4())
    quantity = Service(FixtureClient()).prepare_order(agent, PrepareRequest(**request_data))[
        "snapshot"
    ]["lines"][0]["quantity"]
    assert "shortfall" not in quantity


def test_basket_cap_is_one_hundred_and_the_lookup_cap_stays_the_suppliers_limit():
    from aimo import purchases
    from aimo.schemas import MAX_BASKET_LINES, MAX_LOOKUP_IDS

    assert MAX_BASKET_LINES == 100
    assert MAX_LOOKUP_IDS == purchases.MAX_MATERIALS == SUPPLIER_LIMIT
