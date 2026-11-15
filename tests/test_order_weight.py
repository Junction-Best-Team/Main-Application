"""JNP3-MEA-011: an order whose total weight exceeds 30,000 kg is refused, and the error says so.

Owner (Q-70): "the maximum weight, multiple of units and weight, must be less than 30,000 kg per
order and if that error comes up, just state it". The weight of a line is what is actually bought:
the whole sales units the basket proposes times the kilograms in one sales unit, taken from the
catalogue evidence (the sales unit is KG, the units table has KG, or a known KG measure). Owner
Q-98: where the catalogue gives no kilograms, a litre counts as 1 kg per litre. A product with
neither kilogram nor litre evidence (for example eggs counted in pieces) is not counted and the
error says how many lines were not: nothing else is guessed. Authored fixtures only; the supplier
is never reached for a refused order.
"""

from copy import deepcopy
from datetime import date, timedelta
from fractions import Fraction

import pytest
from supplier_fixture import FixtureClient

from aimo import purchases
from aimo.catalog import line_weight_kg
from aimo.db import Problem
from aimo.purchases import MAX_ORDER_WEIGHT_KG, build_snapshot
from aimo.schemas import PrepareRequest


def patch_products(monkeypatch, mutate):
    original = purchases.load_products

    def wrapped(c, ids):
        products = deepcopy(original(c, ids))
        for pid, change in mutate.items():
            if pid in products:
                change(products[pid])
        return products

    monkeypatch.setattr(purchases, "load_products", wrapped)


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


def test_a_litre_product_without_kilogram_evidence_counts_one_kilogram_per_litre():
    # Q-98: 40,000 L at 1 L per sales unit is 40,000 kg; whole sales units are what is bought
    assert weight(product(), 40_000, "L") == Fraction(40_000)
    assert weight(product(), "10.5", "L") == Fraction(11)


def test_catalogue_kilograms_win_over_the_litre_rule():
    p = product()
    p["measures"]["KG"] = {"status": "known", "value": "0.9", "basis": ["authored"]}
    assert weight(p, 10, "L") == Fraction(9)  # oil: 0.9 kg per litre from the catalogue


def test_a_product_with_no_kilogram_and_no_litre_evidence_is_not_counted_or_guessed():
    eggs = product(measures={"L": {"status": "unknown", "value": None, "basis": []}, "KG": {"status": "unknown", "value": None, "basis": []}})
    assert weight(eggs, 40_000, "ST") is None
    conflicting = product()
    conflicting["measures"]["KG"] = {"status": "conflicting", "value": "1", "basis": []}
    assert weight(conflicting, 5, "L") is None  # conflicting evidence is not replaced by the rule


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


def test_unweighed_lines_are_named_in_the_error(agent, request_data, monkeypatch):
    def no_evidence(product):
        product["measures"] = {
            "L": {"status": "unknown", "value": None, "basis": []},
            "KG": {"status": "unknown", "value": None, "basis": []},
        }

    patch_products(monkeypatch, {"464306": no_evidence})
    lines = [kg("460675", 30_010), {"product_id": "464306", "amount": "5", "unit": "ST"}]
    with pytest.raises(Problem) as error:
        build_snapshot(agent, req(request_data, lines), NoSupplier())
    assert "1 line has no weight" in error.value.message and "not counted" in error.value.message


def test_a_litre_order_counts_one_kilogram_per_litre_and_the_error_says_so(agent, request_data):
    lines = [{"product_id": "464306", "amount": "30001", "unit": "L"}]
    with pytest.raises(Problem) as error:
        build_snapshot(agent, req(request_data, lines), NoSupplier())
    assert error.value.code == "ORDER_WEIGHT_LIMIT_EXCEEDED"
    assert "30,001 kg" in error.value.message and "1 kg per litre" in error.value.message


def test_thirty_thousand_litres_are_still_allowed(agent, request_data):
    lines = [{"product_id": "464306", "amount": "30000", "unit": "L"}]
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
