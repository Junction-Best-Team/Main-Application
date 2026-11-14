"""JNP3-MEA-011: an order whose total weight exceeds 30,000 kg is refused, and the error says so.

Owner (Q-70): "the maximum weight, multiple of units and weight, must be less than 30,000 kg per
order and if that error comes up, just state it". The weight of a line is what is actually bought:
the whole sales units the basket proposes times the kilograms in one sales unit, taken from the
catalogue evidence only (the sales unit is KG, the units table has KG, or a known KG measure).
A line with no kilogram evidence (a litre or piece product without a weight) is not counted:
nothing is guessed. Authored fixtures only; the supplier is never reached for a refused order.
"""

from datetime import date, timedelta
from fractions import Fraction

import pytest

from aimo.catalog import line_weight_kg
from aimo.db import Problem
from aimo.purchases import MAX_ORDER_WEIGHT_KG, build_snapshot
from aimo.schemas import PrepareRequest
from aimo.upstream import FixtureClient


class NoSupplier:
    def lookup(self, *args):
        raise AssertionError("the supplier must not be queried for a refused order")


def req(request_data, lines):
    return PrepareRequest.model_validate(
        {**request_data, "requirements": {}, "lines": lines, "delivery_date": str(date.today() + timedelta(days=2))}
    )


def kg(product_id, amount):
    return {"product_id": product_id, "amount": str(amount), "unit": "KG"}


def product(**changes):
    base = {
        "sales_unit": "ST",
        "base_unit": "ST",
        "units": {"ST": "1"},
        "order_step": "1",
        "conflicts": [],
        "measures": {
            "L": {"status": "known", "value": "1", "basis": ["authored"]},
            "KG": {"status": "unknown", "value": None, "basis": []},
        },
    }
    return base | changes


def weight(p, amount, unit):
    return line_weight_kg(p, amount, unit, True)


# --- how the weight of a line is computed -------------------------------------------------------


def test_the_limit_is_thirty_thousand_kilograms():
    assert MAX_ORDER_WEIGHT_KG == Fraction(30_000)


def test_a_kilogram_product_weighs_the_whole_sales_units_it_buys():
    p = product(sales_unit="KG", base_unit="KG", units={"KG": "1"}, order_step="10")
    assert weight(p, 12, "KG") == Fraction(20)  # 12 kg rounds up to the step of 10


def test_a_litre_line_weighs_through_a_known_kilogram_measure():
    p = product()
    p["measures"]["KG"] = {"status": "known", "value": "1.03", "basis": ["authored"]}
    # 10.5 L is 11 whole sales units (1 L each); 11 x 1.03 kg
    assert weight(p, "10.5", "L") == Fraction("11.33")


def test_pieces_weigh_through_the_sales_unit_weight():
    p = product(units={"ST": "1"})
    p["measures"]["KG"] = {"status": "known", "value": "3", "basis": ["authored"]}
    assert weight(p, 4, "ST") == Fraction(12)


def test_a_line_without_kilogram_evidence_has_no_weight_and_is_not_guessed():
    assert weight(product(), 40_000, "L") is None
    conflicting = product()
    conflicting["measures"]["KG"] = {"status": "conflicting", "value": "1", "basis": []}
    assert weight(conflicting, 5, "L") is None


# --- the order limit through the basket ---------------------------------------------------------


def test_exactly_thirty_thousand_kilograms_is_allowed(agent, request_data):
    snapshot, _, _ = build_snapshot(agent, req(request_data, [kg("460675", 30_000)]), FixtureClient())
    assert snapshot["lines"][0]["quantity"]["sales_quantity"] == "30000"


@pytest.mark.parametrize(
    "lines,weight_text",
    [
        ([kg("460675", 30_010)], "30,010"),
        ([kg("460675", 20_000), kg("460035", 10_002)], "30,002"),
    ],
    ids=["one line", "two lines add up"],
)
def test_more_than_the_limit_is_refused_with_the_limit_and_the_weight(
    agent, request_data, lines, weight_text
):
    with pytest.raises(Problem) as error:
        build_snapshot(agent, req(request_data, lines), NoSupplier())
    assert (error.value.code, error.value.status) == ("ORDER_WEIGHT_LIMIT_EXCEEDED", 422)
    assert "30,000 kg" in error.value.message and "per order" in error.value.message
    assert weight_text + " kg" in error.value.message


def test_the_weight_counts_what_is_bought_not_what_was_asked(agent, request_data):
    # 460675 is sold in steps of 10 kg: 29,995 kg asked is 30,000 bought and still allowed;
    # 30,001 asked is 30,010 bought and refused.
    build_snapshot(agent, req(request_data, [kg("460675", 29_995)]), FixtureClient())
    with pytest.raises(Problem) as error:
        build_snapshot(agent, req(request_data, [kg("460675", 30_001)]), NoSupplier())
    assert "30,010 kg" in error.value.message


def test_unweighed_lines_are_named_in_the_error(agent, request_data):
    lines = [kg("460675", 30_010), {"product_id": "464306", "amount": "5", "unit": "L"}]
    with pytest.raises(Problem) as error:
        build_snapshot(agent, req(request_data, lines), NoSupplier())
    assert "1 line" in error.value.message and "not counted" in error.value.message


def test_a_litre_order_without_weight_evidence_is_not_refused(agent, request_data):
    lines = [{"product_id": "464306", "amount": "40000", "unit": "L"}]
    snapshot, _, _ = build_snapshot(agent, req(request_data, lines), FixtureClient())
    assert "ORDER_WEIGHT_LIMIT_EXCEEDED" not in {r["code"] for r in snapshot["reasons"]}


def test_service_prepare_refuses_without_creating_a_proposal(service, agent, request_data):
    from aimo.db import connection

    request_data["requirements"] = {}
    request_data["lines"] = [kg("460675", 30_010)]
    with pytest.raises(Problem) as error:
        service.prepare_order(agent, PrepareRequest(**request_data))
    assert error.value.code == "ORDER_WEIGHT_LIMIT_EXCEEDED"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0
