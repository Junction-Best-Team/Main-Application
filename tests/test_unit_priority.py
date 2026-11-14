"""BAS-009 (catalog part): one product requested in two units is combined in one priority unit.

Pure tests, authored fixtures only (`aimo.fixtures`), no database, no supplier. The owner's rule:
"The tools backend shall pick one unit by a configured priority order (kg, then L, then pieces)
when the same product is requested in two units." The conversion uses only the catalog evidence
`quantity()` uses (sales unit, `units[].sizeInBaseUnits`, baseUnit KG, `measures` known); there is
no kg<->pieces conversion without it.
"""

import itertools
from decimal import Decimal

import pytest

from aimo import catalog
from aimo.catalog import combine_in_priority_unit, quantity
from aimo.fixtures import fixture_facts


def product(**changes):
    p = fixture_facts()[0]  # milk 464306: sales ST, KI = 20 ST, known 1 L per ST
    p.update(changes)
    return p


def both_measures(kg="0.5", litre="1", **changes):
    """Sold per ST; one ST holds `kg` kg and `litre` L (both known)."""
    p = product(**changes)
    p["measures"] = {
        "KG": {"value": kg, "status": "known", "basis": ["authored.kg"]},
        "L": {"value": litre, "status": "known", "basis": ["authored.l"]},
    }
    return p


def combine(p, *items, **kw):
    return combine_in_priority_unit(p, [(Decimal(a), u) for a, u in items], **kw)


def unknown(result):
    assert result["status"] == "unknown"
    assert result["amount"] is None and result["unit"] is None and result["basis"] == []
    assert result["reason"]
    return result["reason"]


# --- the priority: KG, then L, then pieces ------------------------------------------------


def test_kg_and_l_are_combined_in_kg():
    # 2 KG = 4 ST, 3 L = 3 ST: 7 ST = 3.5 KG
    r = combine(both_measures(), ("2", "KG"), ("3", "L"))
    assert (r["amount"], r["unit"], r["status"]) == ("3.5", "KG", "derived")
    assert "authored.kg" in r["basis"] and "authored.l" in r["basis"]


def test_kg_beats_pieces_only_through_catalog_evidence():
    # 2 KG = 4 ST, plus 10 ST = 14 ST = 7 KG
    r = combine(both_measures(), ("2", "KG"), ("10", "ST"))
    assert (r["amount"], r["unit"]) == ("7", "KG")
    assert "salesUnit" in r["basis"]


def test_l_beats_pieces():
    # milk: 1 ST = 1 L; 10 ST + 2 L = 12 L
    r = combine(product(), ("10", "ST"), ("2", "L"))
    assert (r["amount"], r["unit"], r["status"]) == ("12", "L", "derived")


def test_l_and_a_box_unit_give_l():
    # 1 KI = 20 ST = 20 L; plus 5 L
    r = combine(product(), ("1", "KI"), ("5", "L"))
    assert (r["amount"], r["unit"]) == ("25", "L")
    assert "units.sizeInBaseUnits" in r["basis"]


def test_only_pieces_stay_in_the_sales_unit_when_it_is_requested():
    r = combine(product(), ("3", "ST"), ("4", "ST"))
    assert (r["amount"], r["unit"]) == ("7", "ST")


def test_two_piece_units_use_the_sales_unit_then_alphabetical_not_the_request_order():
    # 1 KI = 20 ST. The sales unit ST wins, in either order of the items.
    for items in itertools.permutations([("1", "KI"), ("5", "ST")]):
        r = combine(product(), *items)
        assert (r["amount"], r["unit"]) == ("25", "ST")
    # Neither requested unit is the sales unit: alphabetical, so the order cannot matter.
    p = product(units={"ST": "1", "KI": "20", "PK": "5"})
    for items in itertools.permutations([("1", "PK"), ("1", "KI")]):
        r = combine(p, *items)
        assert (r["amount"], r["unit"]) == ("1.25", "KI")
    # 1 PK = 5 ST = 0.25 KI, so 1 PK + 1 KI = 1.25 KI


def test_single_item_is_returned_in_its_own_unit():
    r = combine(both_measures(), ("3", "L"))
    assert (r["amount"], r["unit"]) == ("3", "L")


def test_pieces_are_not_turned_into_weight_without_catalog_evidence():
    p = product()  # milk has no known KG
    reason = unknown(combine(p, ("2", "KG"), ("10", "ST")))
    assert "KG" in reason
    # the volume is known, so the same fixture combines ST and L
    assert combine(p, ("2", "L"), ("10", "ST"))["unit"] == "L"


def test_names_and_hints_are_never_conversion_evidence():
    # 465039 is sold per 5-pack and its name says 1 L, but the volume is unverified.
    p = fixture_facts()[3]
    assert p["id"] == "465039" and p["measures"]["L"]["name_hint"] == "1"
    unknown(combine(p, ("1", "L"), ("2", "KI")))


def test_kg_base_unit_product_combines_with_pieces_by_its_own_factors():
    p = product(
        sales_unit="KG",
        base_unit="KG",
        units={"KG": "1", "ST": "0.25"},
        order_step="1",
        variable_weight=False,
    )
    p["measures"] = {
        "KG": {"value": "1", "status": "known", "basis": ["authored.fixture"]},
        "L": {"value": None, "status": "unknown", "basis": []},
    }
    # 1 ST is 0.25 base units, so 1 KG = 4 ST: 2 KG + 4 ST = 3 KG
    r = combine(p, ("2", "KG"), ("4", "ST"))
    assert (r["amount"], r["unit"]) == ("3", "KG")
    # baseUnit KG with no explicit KG factor on a product sold per piece
    q = product(sales_unit="ST", base_unit="KG", units={"ST": "0.4"})
    q["measures"]["L"] = {"value": None, "status": "unknown", "basis": []}
    r = combine(q, ("2", "KG"), ("5", "ST"))
    assert (r["amount"], r["unit"]) == ("4", "KG")  # 5 ST = 2 KG
    assert "baseUnit" in r["basis"]


# --- exactness: no float, no rounding ------------------------------------------------------


def test_thirds_stay_exact():
    # 1 KG = 1/3 ST and 1 L = 2/3 ST: together exactly 1 ST = 3 KG (Decimal(1)/3 would drift)
    p = both_measures(kg="3", litre="1.5")
    r = combine(p, ("1", "KG"), ("1", "L"))
    assert (r["amount"], r["unit"]) == ("3", "KG")
    r = combine(p, ("1", "KG"), ("1", "KG"), ("1", "KG"), ("1", "L"), ("1", "L"), ("1", "L"))
    assert r["amount"] == "9"  # 3 KG + 3 L = 1 + 2 ST = 3 ST


def test_four_decimals_are_kept_exactly():
    r = combine(product(), ("0.0001", "L"), ("1", "ST"))
    assert (r["amount"], r["unit"]) == ("1.0001", "L")


def test_total_needing_more_than_four_decimals_is_unknown_not_rounded():
    r = combine(product(), ("0.00001", "L"), ("1", "ST"))  # 1.00001 L
    assert "decimal" in unknown(r).lower()
    # a repeating decimal: 1 L = 1/3 ST, 1 KG = 7/3 ... total 10/3 KG
    p = both_measures(kg="7", litre="3")
    assert "decimal" in unknown(combine(p, ("1", "L"), ("1", "KG"))).lower()


def test_total_needing_more_than_fourteen_digits_is_unknown():
    assert combine(product(), ("9999999999.9999", "L"), ("0", "ST"))["status"] == "unknown"
    ok = combine(product(), ("9999999999", "L"), ("1", "ST"))
    assert ok["amount"] == "10000000000"
    too_big = combine(product(), ("99999999999999", "L"), ("1", "ST"))
    assert "digit" in unknown(too_big).lower()


# --- unknown cases -------------------------------------------------------------------------


def test_unconvertible_item_makes_the_whole_result_unknown():
    p = fixture_facts()[3]  # box-sold, unknown volume
    assert "L" in unknown(combine(p, ("1", "L"), ("2", "KI")))
    assert "XX" in unknown(combine(product(), ("1", "L"), ("1", "XX")))


def test_conflicting_measure_is_unknown():
    p = product()
    p["measures"]["L"]["status"] = "conflicting"
    unknown(combine(p, ("1", "L"), ("1", "ST")))


def test_conflicting_product_is_unknown():
    unknown(combine(product(conflicts=["UNIT_FACTOR_CONFLICT"]), ("1", "L"), ("1", "ST")))


def test_missing_sales_unit_factor_is_unknown():
    unknown(combine(product(sales_unit="XX"), ("1", "L"), ("1", "ST")))


def test_empty_and_non_positive_requests_are_unknown():
    unknown(combine_in_priority_unit(product(), []))
    unknown(combine(product(), ("0", "L"), ("1", "ST")))
    unknown(combine(product(), ("-1", "L"), ("3", "ST")))


# --- configured priority and order independence -------------------------------------------


def test_priority_is_the_configured_constant(monkeypatch):
    assert catalog.UNIT_PRIORITY == ("KG", "L")
    p = both_measures()
    assert combine(p, ("2", "KG"), ("3", "L"))["unit"] == "KG"
    monkeypatch.setattr(catalog, "UNIT_PRIORITY", ("L", "KG"))
    r = combine(p, ("2", "KG"), ("3", "L"))
    assert (r["amount"], r["unit"]) == ("7", "L")
    monkeypatch.setattr(catalog, "UNIT_PRIORITY", ("KI",))
    r = combine(product(), ("1", "KI"), ("20", "ST"), ("2", "L"))
    assert (r["amount"], r["unit"]) == ("2.1", "KI")  # 1 KI + 20 ST + 2 L = 1 + 1 + 0.1


@pytest.mark.parametrize(
    "items",
    [
        [("2", "KG"), ("3", "L"), ("10", "ST")],
        [("1", "KG"), ("1", "L"), ("1", "ST"), ("1", "KG")],
    ],
)
def test_result_does_not_depend_on_the_order_of_the_items(items):
    p = both_measures()
    results = {repr(combine(p, *perm)) for perm in itertools.permutations(items)}
    assert len(results) == 1
    assert next(iter(results)).count("'unit': 'KG'") == 1


def test_inputs_are_not_modified():
    p = both_measures()
    before = repr(p)
    items = [(Decimal("2"), "KG"), (Decimal("3"), "L")]
    combine_in_priority_unit(p, items)
    assert repr(p) == before and items == [(Decimal("2"), "KG"), (Decimal("3"), "L")]


# --- the piece unit with reviewed count evidence (PR #38) ---------------------------------


def test_piece_unit_uses_count_evidence_when_given():
    evidence = {"piece_per_sales": "12", "source": "recipe_product_evidence"}
    p = product(sales_unit="KI", units={"ST": "1", "KI": "12"})
    r = combine(p, ("24", "piece"), ("1", "KI"), count_evidence=evidence)
    # KI is the sales unit: 24 pieces = 2 KI, so the total is 3 KI
    assert (r["amount"], r["unit"]) == ("3", "KI")
    assert "reviewed_ingredient_count_per_sales_unit" in r["basis"]


def test_piece_unit_without_count_evidence_is_unknown():
    unknown(combine(product(), ("2", "piece"), ("1", "ST")))


# --- quantity() is unchanged ---------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,step,whole,expected,excess",
    [
        ("10", "1", True, "3", "0"),
        ("20", "1.5", True, "6", "0"),
        ("20.0001", "1.5", True, "9", "9.9999"),
    ],
)
def test_quantity_output_is_unchanged(amount, step, whole, expected, excess):
    p = product(units={"ST": "10", "REQUEST": "3"}, order_step=step)
    q = quantity(p, Decimal(amount), "REQUEST", whole)
    assert q["sales_quantity"] == expected and Decimal(q["excess"]) == Decimal(excess)
    assert q["basis"][0] == "units.sizeInBaseUnits"


def test_quantity_keeps_its_unknown_and_conflicting_results():
    p = product()
    p["measures"]["L"]["status"] = "conflicting"
    q = quantity(p, Decimal("2"), "L", True)
    assert q["status"] == "conflicting" and q["basis"] == []
    q = quantity(product(conflicts=["X"]), Decimal("2"), "L", True)
    assert q["status"] == "unknown" and q["sales_quantity"] is None
