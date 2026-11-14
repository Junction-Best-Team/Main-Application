"""Catalog normalisation and quantity conversion: classifications, conflicts and unit rules."""

from decimal import Decimal

import pytest

from aimo.catalog import normalize, quantity, requirement_reasons, search_text
from aimo.fixtures import fixture_facts
from aimo.schemas import Requirements


def raw(**synkka):
    base = {
        "id": "p1",
        "salesUnit": "ST",
        "baseUnit": "ST",
        "allowedLotSize": "1",
        "units": [{"unitId": "ST", "sizeInBaseUnits": 1}, {"unitId": "KI", "sizeInBaseUnits": 10}],
        "synkkaData": {
            "names": [{"language": "en", "value": "Plain thing"}],
            "variableUnit": False,
            "classifications": [],
            "unitConversions": [],
        },
    }
    base["synkkaData"].update(synkka)
    return base


def facts(**overrides):
    p = {k: v for k, v in fixture_facts()[0].items()}
    p.update(overrides)
    return p


# --- normalize -----------------------------------------------------------------------------------


def test_classifications_become_claims_allergens_and_free_from():
    p = normalize(
        raw(
            classifications=[
                {"name": "nutritionalClaim", "values": [{"id": "FREE_FROM_LACTOSE"}]},
                {
                    "name": "allergen",
                    "values": [
                        {"id": "AM", "unit": "CONTAINS"},
                        {"id": "GL", "unit": "MAY_CONTAIN"},
                        {"id": "SO", "unit": "FREE_FROM"},  # not an allergen presence statement
                    ],
                },
                {"name": "nonAllergen", "values": [{"id": "EN", "unit": "FREE_FROM"}]},
                {"name": "nonAllergen", "values": [{"id": "MU", "unit": "OTHER"}]},
                {"name": "unrelated"},  # no values at all
            ]
        ),
        "src",
    )
    assert p["claims"] == ["FREE_FROM_LACTOSE"]
    assert p["allergens"] == {"AM": "CONTAINS", "GL": "MAY_CONTAIN"}
    assert p["free_from"] == ["EN"]
    assert p["allergen_conflicts"] == []


def test_allergen_both_present_and_free_from_is_a_conflict():
    p = normalize(
        raw(
            classifications=[
                {"name": "allergen", "values": [{"id": "AM", "unit": "CONTAINS"}]},
                {"name": "nonAllergen", "values": [{"id": "AM", "unit": "FREE_FROM"}]},
            ]
        ),
        "src",
    )
    assert p["allergen_conflicts"] == ["AM"]


def test_repeated_unit_with_a_different_factor_is_a_conflict_and_blocks_quantities():
    record = raw()
    record["units"].append({"unitId": "KI", "sizeInBaseUnits": 12})
    p = normalize(record, "src")
    assert p["conflicts"] == ["UNIT_FACTOR_CONFLICT"]
    assert quantity(p, Decimal("5"), "KI", True)["sales_quantity"] is None
    record["units"][-1]["sizeInBaseUnits"] = 10  # same factor repeated is harmless
    assert normalize(record, "src")["conflicts"] == []


def test_net_weight_and_volume_are_read_only_from_the_base_unit_entry():
    p = normalize(
        raw(
            unitConversions=[
                {
                    "synkkaPackagingType": "BASE_UNIT_OR_EACH",
                    "netWeight": {"unit": "GRM", "value": 500},
                    "volume": {"unit": "DLT", "value": 5},
                },
                {"synkkaPackagingType": "CASE", "netWeight": {"unit": "KGM", "value": 99}},
            ]
        ),
        "src",
    )
    assert p["measures"]["KG"]["value"] == "0.500" and p["measures"]["KG"]["status"] == "known"
    assert Decimal(p["measures"]["L"]["value"]) == Decimal("0.5")


def test_name_with_a_different_size_marks_volume_conflicting_but_never_creates_it():
    conv = [
        {
            "synkkaPackagingType": "BASE_UNIT_OR_EACH",
            "volume": {"unit": "LTR", "value": 1},
        }
    ]
    named = raw(unitConversions=conv)
    named["synkkaData"]["names"] = [{"language": "fi", "value": "Maito 2,5 dl"}]
    p = normalize(named, "src")
    assert p["measures"]["L"]["name_hint"] == "0.25"
    assert p["measures"]["L"]["status"] == "conflicting"
    no_data = raw()
    no_data["synkkaData"]["names"] = [{"language": "en", "value": "Milk 1 l"}]
    q = normalize(no_data, "src")
    assert q["measures"]["L"]["status"] == "unknown" and q["measures"]["L"]["value"] is None
    assert q["measures"]["L"]["name_hint"] == "1"


def test_multipack_names_are_not_read_as_a_volume():
    named = raw()
    named["synkkaData"]["names"] = [{"language": "en", "value": "Juice 6 x 1 l"}]
    assert "name_hint" not in normalize(named, "src")["measures"]["L"]


def test_missing_variable_unit_flag_defaults_to_variable_weight():
    unknown = raw()
    del unknown["synkkaData"]["variableUnit"]
    assert normalize(unknown, "src")["variable_weight"] is True
    assert normalize(raw(), "src")["variable_weight"] is False


def test_nameless_product_falls_back_to_its_id():
    nameless = raw(names=[])
    assert normalize(nameless, "src")["name"] == "p1"


def test_search_text_contains_id_gtin_names_and_claims():
    text = search_text(facts(gtin="6410000000000", claims=["FREE_FROM_LACTOSE"]))
    assert "464306" in text and "6410000000000" in text and "FREE_FROM_LACTOSE" in text


# --- requirement_reasons -------------------------------------------------------------------------


def codes(p, **req):
    return [r["code"] for r in requirement_reasons(p, Requirements(**req))]


def test_milk_free_requires_an_explicit_declaration():
    assert codes(facts(allergens={}, free_from=["AM"]), milk_free=True) == []
    assert codes(facts(allergens={}, free_from=[]), milk_free=True) == ["MILK_FREE_UNVERIFIED"]
    assert codes(facts(allergens={"AM": "MAY_CONTAIN"}, free_from=[]), milk_free=True) == [
        "MILK_REQUIREMENT_VIOLATED"
    ]


def test_milk_conflict_is_reported_once_as_a_dietary_conflict():
    p = facts(allergens={"AM": "CONTAINS"}, free_from=["AM"], allergen_conflicts=["AM"])
    assert codes(p, milk_free=True) == ["DIETARY_EVIDENCE_CONFLICT"]


def test_lactose_free_needs_the_claim():
    assert codes(facts(claims=[]), lactose_free=True) == ["LACTOSE_FREE_UNVERIFIED"]
    assert codes(facts(), lactose_free=True) == []


# --- quantity ------------------------------------------------------------------------------------


def test_base_unit_kg_is_converted_through_the_sales_unit_factor():
    kg = facts(
        sales_unit="KI",
        base_unit="KG",
        units={"KI": "5"},
        order_step="1",
        measures={
            "L": {"value": None, "status": "unknown", "basis": []},
            "KG": {"value": None, "status": "unknown", "basis": []},
        },
    )
    q = quantity(kg, Decimal("12"), "KG", False)
    assert q["status"] == "derived" and q["sales_quantity"] == "3"  # 12 kg / 5 kg per case, up
    assert q["proposed_amount"] == "15" and q["excess"] == "3"
    assert q["basis"] == ["baseUnit", "units.sizeInBaseUnits"]


def test_conflicting_measure_stays_conflicting_and_unconverted():
    p = facts(
        measures={
            "L": {"value": None, "status": "conflicting", "basis": []},
            "KG": {"value": None, "status": "unknown", "basis": []},
        }
    )
    q = quantity(p, Decimal("5"), "L", True)
    assert q["status"] == "conflicting" and q["sales_quantity"] is None


@pytest.mark.parametrize("step", ["0", "-1", "0.0"])
def test_non_positive_order_step_is_unresolved(step):
    q = quantity(facts(order_step=step), Decimal("5"), "ST", True)
    assert q["sales_quantity"] is None and q["status"] == "unknown"


def test_unknown_unit_and_zero_factors_are_unresolved():
    assert quantity(facts(), Decimal("5"), "FURLONG", True)["sales_quantity"] is None
    assert quantity(facts(units={"ST": "0"}), Decimal("5"), "ST", True)["sales_quantity"] is None
    assert (
        quantity(facts(units={"ST": "1", "KI": "0"}), Decimal("5"), "KI", True)["sales_quantity"]
        is None
    )


def test_whole_packs_round_the_step_up_to_a_whole_sales_unit():
    p = facts(order_step=".25")
    whole = quantity(p, Decimal("1.1"), "ST", True)
    assert whole["sales_quantity"] == "2" and whole["effective_step"] == "1"
    loose = quantity(p, Decimal("1.1"), "ST", False)
    assert loose["sales_quantity"] == "1.25" and loose["effective_step"] == "0.25"


def test_measure_conversion_uses_its_basis():
    q = quantity(facts(), Decimal("2.5"), "L", True)
    assert q["sales_quantity"] == "3" and q["excess"] == "0.5"
    assert q["basis"][0] == "fixture.base_volume"
