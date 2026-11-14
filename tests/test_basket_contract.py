"""Basket contract: JNP3-BAS-001 to BAS-005 (whole packs, combining, conversion, excess, exactness).

Authored fixtures only (`aimo.fixtures`, `FixtureClient`); no live supplier data. What
`tests/test_arithmetic_contract.py` already proves (lot size, required vs purchased amount,
deposit equality, float AST guard) is not repeated here. Strict xfail tests mark requirement
gaps that an API exists to call; each must fail today with an AssertionError and turns into an
error (XPASS strict) once the gap is closed, which is the signal to remove the marker.
"""

import json
import math
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aimo.agent_tools import ToolSession
from aimo.catalog import quantity
from aimo.db import Problem, connection, js
from aimo.fixtures import fixture_facts
from aimo.purchases import money
from aimo.schemas import LineRequest, PrepareRequest, PurchaseRequest
from aimo.service import Service
from aimo.upstream import FixtureClient


def product(index=0, **changes):
    """Fresh copy of an authored fixture product (0 = milk, 3 = box-sold 465039)."""
    p = fixture_facts()[index]
    p.update(changes)
    return p


def prepare(service, agent, request_data, lines, **changes):
    request_data.update(idempotency_key=str(uuid4()), lines=lines, requirements={}, **changes)
    return service.prepare_order(agent, PrepareRequest(**request_data))


# --- BAS-001: basket of whole packs ----------------------------------------------------------


def test_default_policy_requires_whole_sales_units(agent):
    with connection() as c:
        rules = c.execute("SELECT rules FROM policies WHERE buyer_id='demo-hotel'").fetchone()
    assert rules["rules"]["whole_sales_units"] is True


def test_basket_lines_are_whole_packs_and_cover_the_need(service, agent, request_data):
    needs = {  # product -> (amount, unit, expected whole packs)
        "464306": ("10.5", "L", 11),
        "464398": ("0.3", "L", 1),
        "463380": ("7", "L", 7),
        "460123": ("30", "BOT", 3),  # 12 bottles per box: 2.5 boxes needed, 3 sold
    }
    lines = [{"product_id": k, "amount": a, "unit": u} for k, (a, u, _) in needs.items()]
    snapshot = prepare(service, agent, request_data, lines)["snapshot"]
    assert [line["product_id"] for line in snapshot["lines"]] == list(needs)
    for line in snapshot["lines"]:
        q, (amount, unit, packs) = line["quantity"], needs[line["product_id"]]
        assert q["status"] == "derived" and q["requested_unit"] == unit
        bought = Fraction(q["sales_quantity"])
        assert bought.denominator == 1 and bought == packs  # whole packs, no fractions
        assert Fraction(q["proposed_amount"]) >= Fraction(amount)  # the need is covered
        assert "buyer_policy.whole_sales_units" in q["basis"]


def test_whole_pack_rule_is_a_policy_flag_not_a_guarantee(service, agent, request_data):
    # Conditional part of BAS-001: with the flag off the same need is met by a fractional pack.
    with connection() as c:
        rules = c.execute("SELECT rules FROM policies WHERE buyer_id='demo-hotel'").fetchone()[
            "rules"
        ]
        rules["whole_sales_units"] = False
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)", (js(rules),)
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    lines = [{"product_id": "464306", "amount": "10.5", "unit": "L"}]
    q = prepare(service, agent, request_data, lines)["snapshot"]["lines"][0]["quantity"]
    assert Decimal(q["sales_quantity"]) == Decimal("10.5")  # not a whole pack
    assert "buyer_policy.whole_sales_units" not in q["basis"]


# --- BAS-002: same product combined into one line, contributions kept ------------------------


def tool_session(agent, service):
    return ToolSession(dict(agent) | {"_turn_id": str(uuid4())}, service)


def milk_plan(*parts):
    """Meal plan whose ingredients all use the authored milk product (464306)."""
    return {
        "title": "Milk dishes",
        "portions": 10,
        "ingredients": [
            {"name": name, "amount": amount, "unit": unit, "product_id": "464306"}
            for name, amount, unit in parts
        ],
    }


def basket(*lines, delivery_date):
    return {
        "request_id": "milk-dishes",
        "destination": "hotel-helsinki",
        "delivery_date": delivery_date,
        "lines": [{"product_id": "464306", "amount": a, "unit": u} for a, u in lines],
    }


def milk_session(agent, service, *parts):
    session = tool_session(agent, service)
    session.invoke("get_product", json.dumps({"product_id": "464306"}))
    session.invoke("publish_meal_plan", json.dumps(milk_plan(*parts)))
    return session


def test_schema_rejects_two_lines_for_one_product(request_data):
    request_data.pop("idempotency_key")
    request_data["lines"] *= 2
    with pytest.raises(ValidationError, match="Combine quantities for duplicate product IDs"):
        PurchaseRequest(**request_data)


def test_tool_prepares_the_combined_line_and_rejects_uncombined_ones(agent, service, request_data):
    when = request_data["delivery_date"]
    session = milk_session(agent, service, ("cream sauce", "5", "L"), ("soup", "5.5", "L"))
    with pytest.raises(Problem) as error:  # two lines for one product: not accepted as typed args
        session.invoke(
            "prepare_order", json.dumps(basket(("5", "L"), ("5.5", "L"), delivery_date=when))
        )
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"
    with pytest.raises(Problem) as error:  # one line, wrong sum
        session.invoke("prepare_order", json.dumps(basket(("10", "L"), delivery_date=when)))
    assert error.value.code == "MEAL_BASKET_MISMATCH"
    proposal = session.invoke(
        "prepare_order", json.dumps(basket(("10.5", "L"), delivery_date=when))
    )
    lines = proposal["snapshot"]["lines"]
    assert [(line["product_id"], line["quantity"]["requested_amount"]) for line in lines] == [
        ("464306", "10.5")
    ]


def test_combined_line_keeps_each_contributing_ingredient(agent, service, request_data):
    when = request_data["delivery_date"]
    session = milk_session(agent, service, ("cream sauce", "5", "L"), ("soup", "5.5", "L"))
    proposal = session.invoke(
        "prepare_order", json.dumps(basket(("10.5", "L"), delivery_date=when))
    )
    line = proposal["snapshot"]["lines"][0]
    contributions = line.get("contributions")
    assert contributions is not None, f"no contributions on the line; keys: {sorted(line)}"
    assert [(c["ingredient"], c["amount"]) for c in contributions] == [
        ("cream sauce", "5"),
        ("soup", "5.5"),
    ]


def test_one_product_in_two_units_can_be_prepared(agent, service, request_data):
    when = request_data["delivery_date"]
    session = milk_session(agent, service, ("sauce", "5", "L"), ("garnish", "1", "KI"))
    shapes = [
        basket(("5", "L"), ("1", "KI"), delivery_date=when),
        basket(("5", "L"), delivery_date=when),
        basket(("1", "KI"), delivery_date=when),
        basket(("25", "L"), delivery_date=when),  # 5 L + 1 KI converted (20 per KI)
    ]
    codes = []
    for shape in shapes:
        try:
            session.invoke("prepare_order", json.dumps(shape))
            return
        except Problem as error:
            codes.append(error.code)
    raise AssertionError(f"every basket shape was rejected: {codes}")


# --- BAS-003: conversion with catalog evidence -----------------------------------------------

CASES = [
    # unit, amount, expected sales quantity, expected basis
    ("ST", "7", "7", ["salesUnit", "buyer_policy.whole_sales_units"]),
    ("KI", "3", "60", ["units.sizeInBaseUnits", "buyer_policy.whole_sales_units"]),
    (
        "L",
        "10.5",
        "11",
        ["authored.fixture", "units.sizeInBaseUnits", "buyer_policy.whole_sales_units"],
    ),
]


def test_conversion_names_the_catalog_evidence_it_used():
    p = product()
    p["measures"]["L"]["basis"] = ["authored.fixture"]
    for unit, amount, packs, basis in CASES:
        q = quantity(p, Decimal(amount), unit, True)
        assert (q["status"], q["sales_quantity"], q["basis"]) == ("derived", packs, basis), unit


def test_base_unit_kilogram_path_uses_the_sales_unit_size():
    # 1 KI = 5 kg of base unit; 12 kg need 3 boxes.
    p = product(sales_unit="KI", base_unit="KG", units={"KI": "5"})
    q = quantity(p, Decimal("12"), "KG", True)
    assert q["sales_quantity"] == "3" and q["basis"][:2] == ["baseUnit", "units.sizeInBaseUnits"]


def test_reviewed_piece_count_is_the_only_basis_for_pieces():
    p = product()
    assert quantity(p, Decimal("10"), "piece", True)["sales_quantity"] is None
    evidence = {"piece_per_sales": "4", "source": "authored.count"}
    q = quantity(p, Decimal("10"), "piece", True, count_evidence=evidence)
    assert q["sales_quantity"] == "3" and q["basis"][0] == "authored.count"  # 10 / 4 -> 3 packs


@pytest.mark.parametrize(
    "unit,changes,status",
    [
        ("BOX", {}, "unknown"),  # a unit the catalog does not know
        ("KG", {}, "unknown"),  # known dimension, no measure value
        (
            "L",
            {
                "measures": {
                    "L": {"value": None, "status": "unknown", "basis": [], "name_hint": "1"}
                }
            },
            "unknown",
        ),
        (
            "L",
            {"measures": {"L": {"value": "1", "status": "conflicting", "basis": []}}},
            "conflicting",
        ),
        ("ST", {"conflicts": ["units"]}, "unknown"),
    ],
)
def test_no_evidence_means_no_conversion(unit, changes, status):
    q = quantity(product(**deepcopy(changes)), Decimal("10"), unit, True)
    assert q["sales_quantity"] is None and q["proposed_amount"] is None
    assert q["excess"] is None and q["status"] == status


def test_unconvertible_line_blocks_the_total_instead_of_guessing(service, agent, request_data):
    lines = [
        {"product_id": "464306", "amount": "10", "unit": "L"},
        {"product_id": "463380", "amount": "10", "unit": "BOX"},
    ]
    proposal = prepare(service, agent, request_data, lines)
    codes = {(r["code"], r["product_id"]) for r in proposal["snapshot"]["reasons"]}
    assert ("QUANTITY_UNRESOLVED", "463380") in codes and proposal["snapshot"][
        "gross_total"
    ] is None
    assert proposal["snapshot"]["lines"][1]["gross"] is None
    assert proposal["policy_outcome"] == "needs_resolution"


# --- BAS-004: excess or shortfall per line ---------------------------------------------------


@pytest.mark.parametrize("step", ["1", "1.5", ".01", "6"])
def test_excess_is_never_negative_and_matches_purchased_minus_required(step):
    # 2.5 REQUEST units per pack, a terminating ratio so every rendered string is exact.
    p = product(units={"ST": "10", "REQUEST": "4"}, order_step=step)
    for hundredths in range(1, 400, 7):
        need = Decimal(hundredths) / 100
        q = quantity(p, need, "REQUEST", True)
        bought = Fraction(q["sales_quantity"]) * Fraction(5, 2)
        assert Fraction(q["proposed_amount"]) == bought
        assert Fraction(q["excess"]) == bought - Fraction(need) >= 0


def test_excess_is_zero_only_for_an_exact_fit():
    p = product(units={"ST": "10", "REQUEST": "3"}, order_step="1")
    assert Decimal(quantity(p, Decimal("30"), "REQUEST", True)["excess"]) == 0
    assert Decimal(quantity(p, Decimal("30.0001"), "REQUEST", True)["excess"]) > 0


def test_box_line_reports_excess_in_the_requested_unit(service, agent, request_data):
    lines = [{"product_id": "460123", "amount": "30", "unit": "BOT"}]
    q = prepare(service, agent, request_data, lines)["snapshot"]["lines"][0]["quantity"]
    assert (q["sales_quantity"], q["proposed_amount"], q["excess"]) == ("3", "36", "6")


class ShortStock(FixtureClient):
    def __init__(self):
        super().__init__()
        self.stock = {"464306": "3"}


def test_short_stock_is_reported_as_a_reason_with_the_available_amount(agent, request_data):
    lines = [{"product_id": "464306", "amount": "10", "unit": "L"}]
    snapshot = prepare(Service(ShortStock()), agent, request_data, lines)["snapshot"]
    reason = next(r for r in snapshot["reasons"] if r["code"] == "INSUFFICIENT_STOCK")
    assert reason["product_id"] == "464306" and "Only 3 ST available" in reason["message"]
    assert snapshot["lines"][0]["quantity"]["sales_quantity"] == "10"


def test_shortfall_is_a_numeric_field_on_the_line(agent, request_data):
    lines = [{"product_id": "464306", "amount": "10", "unit": "L"}]
    line = prepare(Service(ShortStock()), agent, request_data, lines)["snapshot"]["lines"][0]
    # 10 packs wanted, 3 available: 7 packs short (BAS-008: `shortfall`, in sales units).
    assert line["quantity"].get("shortfall") == "7", f"quantity keys: {sorted(line['quantity'])}"


# --- BAS-005: exact quantities, decimal money ------------------------------------------------


def test_money_rounds_half_up_on_decimals_where_binary_floats_would_not():
    assert money(Decimal("2.675")) == Decimal("2.68") and round(2.675, 2) == 2.67  # float trap
    assert money(Decimal("0.005")) == Decimal("0.01") and money(Decimal("1.004")) == Decimal("1.00")
    assert str(money(Decimal("3"))) == "3.00"


def test_json_numbers_enter_as_exact_decimals():
    line = LineRequest.model_validate_json('{"product_id":"x","amount":0.1,"unit":"L"}')
    assert line.amount == Decimal("0.1") and not isinstance(line.amount, float)


def test_ceiling_is_exact_where_float_division_rounds_the_wrong_way():
    # 2.1 L at 0.3 L per pack is exactly 7 packs; float(2.1) / float(0.3) is 7.000000000000001.
    assert math.ceil(2.1 / 0.3) == 8
    p = product(units={"ST": "3", "REQUEST": "10"}, order_step="1")  # 0.3 REQUEST per pack
    q = quantity(p, Decimal("2.1"), "REQUEST", True)
    assert (q["sales_quantity"], q["excess"]) == ("7", "0")


def test_priced_pack_count_is_always_an_exact_decimal():
    # Prices use Decimal(sales_quantity): exact as long as the step comes from a decimal string.
    for step in ("1", ".01", "1.5", "0.25", "6"):
        p = product(units={"ST": "7", "REQUEST": "3"}, order_step=step)
        for whole in (True, False):
            q = quantity(p, Decimal("0.4"), "REQUEST", whole)
            assert Fraction(Decimal(q["sales_quantity"])) == Fraction(q["sales_quantity"])


def test_snapshot_money_is_two_decimal_strings_that_add_up(service, agent, request_data):
    lines = [
        {"product_id": "464306", "amount": "10.5", "unit": "L"},
        {"product_id": "460123", "amount": "30", "unit": "BOT"},
    ]
    snapshot = prepare(service, agent, request_data, lines)["snapshot"]
    for field in ("net_total", "gross_total", "tax_total", "deposits_gross"):
        assert Decimal(snapshot[field]).as_tuple().exponent == -2, field
    assert sum(Decimal(line["gross"]) for line in snapshot["lines"]) == Decimal(
        snapshot["gross_total"]
    )
    assert Decimal(snapshot["gross_total"]) - Decimal(snapshot["net_total"]) == Decimal(
        snapshot["tax_total"]
    )


def test_amount_field_cannot_hold_a_nonterminating_quantity():
    # Weakness (a): 50/3 kg can only be sent rounded to 4 decimals, or not at all.
    with pytest.raises(ValidationError):
        LineRequest(product_id="x", amount="16.66666", unit="KG")
    assert LineRequest(product_id="x", amount="16.6667", unit="KG").amount != Decimal(50) / 3


def test_nonterminating_proposed_amount_and_excess_are_decimal_renderings():
    # Weakness (c), display only: the packs are exact, proposed/excess are 50-digit strings.
    # Characterisation: when proposed_amount/excess gain an exact form, update this test.
    p = product(units={"ST": "1", "REQUEST": "3"}, order_step="1")  # one pack covers 1/3 REQUEST
    q = quantity(p, Decimal("0.4"), "REQUEST", True)
    assert q["sales_quantity"] == "2"
    assert Fraction(q["proposed_amount"]) != Fraction(2, 3)  # string is a rounded 2/3
    assert Fraction(q["proposed_amount"]) - Fraction(2, 3) != 0 and len(q["proposed_amount"]) > 40
    assert Fraction(q["excess"]) > 0  # the decision (excess > 0) was taken on exact Fractions


class ThirdDeposit(FixtureClient):
    """Deposit material priced at 0.165 EUR (a half-cent tie after dividing by three)."""

    def lookup(self, customer, ids, delivery_date):
        raw = super().lookup(customer, ids, delivery_date)
        for row in raw["price"]["products"]:
            if row["productId"] == "demo-deposit":
                row["catalogPrice"]["value"] = row["catalogPrice"]["valueWithTax"] = "0.165"
                row["priceWithTax"]["value"] = "0.165"
                row["tax"] = {"taxRate": "0", "taxValue": "0.000"}
        return raw


def test_deposit_charge_for_a_third_of_a_unit_equals_the_exact_rational_result(
    monkeypatch, agent, request_data
):
    from aimo import purchases

    real = purchases.load_products

    def one_third_deposit(c, ids):
        found = real(c, ids)
        for p in found.values():
            if p["id"] == "460123":
                p["deposits"] = [{"material": "demo-deposit", "quantity": "1", "unit": "ST"}]
            if p["id"] == "demo-deposit":  # 1 source unit = 1/3 of a sales unit
                p.update(sales_unit="KI", units={"ST": "1", "KI": "3"})
        return found

    monkeypatch.setattr(purchases, "load_products", one_third_deposit)
    lines = [{"product_id": "460123", "amount": "1", "unit": "KI"}]
    line = prepare(Service(ThirdDeposit()), agent, request_data, lines)["snapshot"]["lines"][0]
    exact = Fraction(1) * Fraction(1, 3) * Fraction("0.165")  # 0.055 exactly
    expected = Decimal(math.floor(exact * 100 + Fraction(1, 2))) / 100  # half up
    assert expected == Decimal("0.06")
    assert line["deposit_lines"][0]["gross"] == str(expected), line["deposit_lines"][0]


# --- BAS-005 / PRP-006: exact deposit pricing must not disturb exact cases or retries --------


def test_exact_deposit_lines_are_identical_to_the_legacy_decimal_calculation(
    service, agent, request_data
):
    """Whole-number ratios give the same net, gross and text as before the rational pricing.

    The text of `priced_sales_quantity` is hashed into the material fingerprint, so an exact
    case must not change it (a proposal prepared earlier must still match on commit).
    """
    lines = [{"product_id": "460123", "amount": "10", "unit": "KI"}]
    line = prepare(service, agent, request_data, lines)["snapshot"]["lines"][0]
    deposit = line["deposit_lines"][0]
    units = Decimal(line["quantity"]["sales_quantity"]) * Decimal("12")
    legacy_priced = units * Decimal("1") / Decimal("1")  # the old Decimal formula
    evidence = deposit["evidence"]
    assert deposit["quantity"] == str(units)
    assert deposit["priced_sales_quantity"] == str(legacy_priced)
    assert deposit["net"] == str(money(legacy_priced * Decimal(evidence["net"])))
    assert deposit["gross"] == str(money(legacy_priced * Decimal(evidence["gross"])))


def test_same_prepare_key_returns_the_stored_proposal_without_pricing_again(
    monkeypatch, agent, request_data
):
    """A retry is resolved by key from the saved revision, so a pricing change cannot alter it."""
    from aimo import purchases

    class SupplierMustNotBeCalled:
        def lookup(self, *args):
            raise AssertionError("a completed preparation retry must not call the supplier")

    request_data.update(
        idempotency_key="deposit-retry-key-0001",
        requirements={},
        lines=[{"product_id": "460123", "amount": "10", "unit": "KI"}],
    )
    request = PrepareRequest(**request_data)
    first = Service(FixtureClient()).prepare_order(agent, request)

    def forbidden(value):
        raise AssertionError("retry recomputed deposit money")

    monkeypatch.setattr(purchases, "exact_money", forbidden)
    again = Service(SupplierMustNotBeCalled()).prepare_order(agent, request)
    assert again["proposal_id"] == first["proposal_id"] and again["revision"] == first["revision"]
    assert again["snapshot"]["gross_total"] == first["snapshot"]["gross_total"]
    assert again["snapshot"]["deposits_gross"] == first["snapshot"]["deposits_gross"]
