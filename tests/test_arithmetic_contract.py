"""Arithmetic contract for the basket: lot size, required vs purchased, deposits, no floats.

Covers JNP3-BAS-006, JNP3-MEA-009, JNP3-PRP-006, JNP3-BAS-005 and the owner's BAS-007
decision (warn only). All products and prices are authored fixtures (`aimo.fixtures`,
`FixtureClient`), never live supplier data. Nothing here touches the database except the
service-level tests, which use the shared `_test` database fixtures from `conftest.py`.
"""

import ast
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import pytest

from aimo.catalog import normalize, quantity
from aimo.fixtures import fixture_facts
from aimo.purchases import money
from aimo.schemas import PrepareRequest
from aimo.service import Service
from aimo.upstream import FixtureClient

SRC = Path(__file__).resolve().parents[1] / "src" / "aimo"


def product(**changes):
    """Fresh copy of the authored milk fixture with the given facts replaced."""
    p = fixture_facts()[0]
    p.update(changes)
    return p


def kg_product(step):
    return product(
        sales_unit="KG",
        base_unit="KG",
        units={"KG": "1"},
        order_step=step,
        variable_weight=False,
        measures={
            "KG": {"value": "1", "status": "known", "basis": ["authored.fixture"]},
            "L": {"value": None, "status": "unknown", "basis": []},
        },
    )


# --- BAS-006: purchased quantity is a multiple of the allowed lot size -----------------------


@pytest.mark.parametrize("whole_packs", [True, False])
@pytest.mark.parametrize(
    "need,sales_quantity,excess",
    [
        ("7", "12", "5"),
        ("6", "6", "0"),
        ("6.0001", "12", "5.9999"),
        ("1", "6", "5"),
        ("13", "18", "5"),
    ],
)
def test_lot_size_six_rounds_up_to_the_next_multiple(whole_packs, need, sales_quantity, excess):
    p = product(units={"ST": "1"}, order_step="6")
    q = quantity(p, Decimal(need), "ST", whole_packs)
    assert q["status"] == "derived"
    assert Decimal(q["sales_quantity"]) == Decimal(sales_quantity)
    assert Decimal(q["excess"]) == Decimal(excess)


@pytest.mark.parametrize("whole_packs", [True, False])
def test_kilogram_lot_size_is_kept_even_when_whole_packs_are_required(whole_packs):
    # Weight-sold goods keep their stated step; the whole-pack rule only applies to other units.
    q = quantity(kg_product("3.0"), Decimal("4"), "KG", whole_packs)
    assert Decimal(q["sales_quantity"]) == 6 and Decimal(q["excess"]) == 2


def test_every_purchased_quantity_is_an_exact_multiple_of_the_lot_size():
    p = product(units={"ST": "1"}, order_step="6")
    for need in range(1, 61):
        q = quantity(p, Decimal(need), "ST", True)
        bought = Fraction(q["sales_quantity"])
        assert bought % 6 == 0 and bought >= need and bought - need < 6


def test_missing_lot_size_leaves_the_line_unresolved_instead_of_guessing():
    q = quantity(product(order_step="0"), Decimal("7"), "ST", True)
    assert q["sales_quantity"] is None and q["status"] == "unknown"


# --- MEA-009: required amount stays separate from the pack-rounded purchased amount ----------


def test_required_amount_is_kept_next_to_the_rounded_purchase():
    p = product(units={"ST": "10", "REQUEST": "3"}, order_step="1.5")
    q = quantity(p, Decimal("20.0001"), "REQUEST", True)
    assert q["requested_amount"] == "20.0001" and q["requested_unit"] == "REQUEST"
    assert Decimal(q["proposed_amount"]) == 30 and q["sales_unit"] == "ST"
    assert Decimal(q["sales_quantity"]) == 9
    assert Decimal(q["proposed_amount"]) - Decimal(q["requested_amount"]) == Decimal(q["excess"])
    exact = quantity(p, Decimal("20"), "REQUEST", True)
    assert exact["requested_amount"] == "20" and Decimal(exact["excess"]) == 0


def test_proposal_line_keeps_required_and_purchased_amounts(service, agent, request_data):
    request_data["lines"] = [{"product_id": "464306", "amount": "10.5", "unit": "L"}]
    proposal = service.prepare_order(agent, PrepareRequest(**request_data))
    q = proposal["snapshot"]["lines"][0]["quantity"]
    assert q["requested_amount"] == "10.5" and q["requested_unit"] == "L"
    assert Decimal(q["sales_quantity"]) == 11 and Decimal(q["proposed_amount"]) == 11
    assert Decimal(q["excess"]) == Decimal("0.5")
    assert proposal["request"]["lines"][0]["amount"] == "10.5"  # the request is not overwritten


# --- PRP-006: deposit charges are part of the proposal total ---------------------------------


def deposit_request(request_data):
    request_data.update(
        requirements={},
        idempotency_key=str(uuid4()),
        lines=[{"product_id": "460123", "amount": "10", "unit": "KI"}],
    )
    return PrepareRequest(**request_data)


def test_gross_total_equals_line_price_plus_deposits(service, agent, request_data):
    snapshot = service.prepare_order(agent, deposit_request(request_data))["snapshot"]
    line = snapshot["lines"][0]
    price_only = money(
        Decimal(line["quantity"]["sales_quantity"]) * Decimal(line["commercial_evidence"]["gross"])
    )
    deposits = sum((Decimal(d["gross"]) for d in line["deposit_lines"]), Decimal(0))
    assert deposits > 0
    assert Decimal(snapshot["deposits_gross"]) == deposits == Decimal(line["deposits_gross"])
    assert Decimal(line["gross"]) == price_only + deposits
    assert Decimal(snapshot["gross_total"]) == price_only + deposits != price_only


class DepositWithoutPrice(FixtureClient):
    """Supplier answers for the product but marks the deposit material's price as an error."""

    def lookup(self, customer, ids, delivery_date):
        raw = super().lookup(customer, ids, delivery_date)
        for row in raw["price"]["products"]:
            if row["productId"] == "demo-deposit":
                row["error"] = True
        return raw


def test_unknown_deposit_price_blocks_the_total_instead_of_counting_zero(agent, request_data):
    proposal = Service(DepositWithoutPrice()).prepare_order(agent, deposit_request(request_data))
    snapshot = proposal["snapshot"]
    codes = {r["code"] for r in snapshot["reasons"]}
    assert {"DEPOSIT_UNRESOLVED", "TOTAL_UNRESOLVED"} <= codes
    assert snapshot["gross_total"] is None and snapshot["deposits_gross"] is None
    # Not asserted: the line itself still shows the price without deposits (see the WS-B audit).
    assert proposal["policy_outcome"] == "needs_resolution"


# --- BAS-005: quantity and money paths contain no binary floating point ----------------------

ARITHMETIC_MODULES = [
    "catalog.py",
    "numeric.py",
    "purchases.py",
    "approval_policy.py",
    "approval_workflow.py",
    "service.py",
    "recipes.py",  # present once recipe planning is merged
]


def float_uses(source):
    """Line numbers of `float(...)` calls and float literals in Python source."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float")
        or (isinstance(node, ast.Constant) and isinstance(node.value, float))
    ]


def test_float_guard_detects_both_call_and_literal():
    assert float_uses("x = float(y)\nz = 0.5\nw = Decimal('0.5')\n") == [1, 2]
    assert float_uses("from fractions import Fraction\nFraction(1, 3)\n") == []


@pytest.mark.parametrize("name", ARITHMETIC_MODULES)
def test_arithmetic_modules_use_no_float(name):
    path = SRC / name
    if not path.exists():
        pytest.skip(f"{name} does not exist on this branch")
    assert float_uses(path.read_text()) == [], f"binary float in {name}"


# --- BAS-007 (owner decision 2026-11-14): variable weight is flagged, never blocking ---------


def test_missing_variable_unit_is_still_flagged_as_variable_weight():
    # Unknown stays flagged (fail-closed flag); the open question is only what the flag causes.
    raw = {
        "id": "synthetic-variable",
        "salesUnit": "KG",
        "baseUnit": "KG",
        "allowedLotSize": "3",
        "units": [{"unitId": "KG", "sizeInBaseUnits": 1}],
        "synkkaData": {"names": [{"language": "en", "value": "Test weight good"}]},
    }
    assert normalize(raw, "authored-test")["variable_weight"] is True
    raw["synkkaData"]["variableUnit"] = False
    assert normalize(raw, "authored-test")["variable_weight"] is False


def test_variable_weight_line_is_flagged_but_does_not_block(service, agent, request_data):
    request_data["requirements"] = {}  # the fixture's lactose-free default would block this product
    request_data["lines"] = [{"product_id": "460675", "amount": "12", "unit": "KG"}]
    proposal = service.prepare_order(agent, PrepareRequest(**request_data))
    flagged = [r for r in proposal["reasons"] if r["code"].startswith("VARIABLE_WEIGHT")]
    assert [r["product_id"] for r in flagged] == ["460675"]  # still flagged for the buyer
    assert proposal["policy_outcome"] != "needs_resolution"  # but not a blocker
