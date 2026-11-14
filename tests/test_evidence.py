from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest

from aimo.approval_policy import evaluate_purchase
from aimo.catalog import normalize, quantity, requirement_reasons
from aimo.db import connection, fingerprint, now
from aimo.fixtures import fixture_facts
from aimo.ingest import publish
from aimo.schemas import Requirements, SearchRequest
from aimo.search import search_products
from aimo.upstream import FixtureClient, validate_lookup


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda r: r["price"]["products"][0].update(catalogPrice=None), "MISSING_PRICE"),
        (
            lambda r: r["price"]["products"][0]["catalogPrice"].update(validTo="2020-01-01"),
            "PRICE_OUTSIDE_VALIDITY",
        ),
        (lambda r: r["price"]["products"][0]["tax"].update(taxRate="25.5"), "MISSING_PRICE"),
        (lambda r: r["price"].update(customerId="wrong"), "UPSTREAM_CONTEXT_MISMATCH"),
        (
            lambda r: r["price"].update(products=r["price"]["products"] * 2),
            "UPSTREAM_PRODUCT_MISMATCH",
        ),
        (
            lambda r: r["availability"]["products"][0].update(scheduleLines=[]),
            "DELIVERY_UNRESOLVED",
        ),
        (
            lambda r: r["availability"]["products"][0].update(logisticModel="Terminal"),
            "UNVERIFIED_STOCK",
        ),
        (
            lambda r: r["availability"]["products"][0]["scheduleLines"][0].update(
                availableAmount="9999999999"
            ),
            "UNVERIFIED_STOCK",
        ),
        (
            lambda r: r["availability"]["products"][0].update(closingTime="2020-01-01T15:00:00"),
            "CUTOFF_PASSED",
        ),
        (
            lambda r: r["availability"]["products"][0]["scheduleLines"][0].update(
                salesUnit="MYSTERY"
            ),
            "AVAILABILITY_UNIT_UNKNOWN",
        ),
        (
            lambda r: r["availability"]["products"][0]["scheduleLines"][0].update(salesBlock=True),
            "SALES_BLOCK",
        ),
        (
            lambda r: r["availability"]["products"][0]["scheduleLines"][0].update(
                availableDate="2099-01-01"
            ),
            "DELIVERY_TOO_LATE",
        ),
    ],
)
def test_supplier_regressions(mutation, code):
    delivery = date.today() + timedelta(days=2)
    raw = FixtureClient().lookup("123", ["464306"], delivery)
    mutation(raw)
    result = validate_lookup(
        raw, "123", ["464306"], delivery, {"464306": fixture_facts()[0]}, now()
    )
    assert code in {r["code"] for r in result["464306"]["reasons"]}


def test_sales_unit_mismatch_converts_only_known_factors():
    delivery = date.today() + timedelta(days=2)
    raw = FixtureClient().lookup("123", ["464306"], delivery)
    raw["availability"]["products"][0]["scheduleLines"][0].update(
        salesUnit="KI", availableAmount="2"
    )
    result = validate_lookup(
        raw, "123", ["464306"], delivery, {"464306": fixture_facts()[0]}, now()
    )["464306"]
    assert not result["reasons"]
    assert Decimal(result["available_sales_quantity"]) == 40


def raw_product():
    return {
        "id": "synthetic-test",
        "salesUnit": "ST",
        "baseUnit": "ST",
        "allowedLotSize": ".01",
        "units": [{"unitId": "ST", "sizeInBaseUnits": 1}, {"unitId": "KI", "sizeInBaseUnits": 20}],
        "synkkaData": {
            "names": [{"language": "en", "value": "Test milk 1 l"}],
            "variableUnit": False,
            "classifications": [],
            "unitConversions": [
                {
                    "synkkaPackagingType": "BASE_UNIT_OR_EACH",
                    "volume": {"unit": "LTR", "value": 1},
                    "grossWeight": {"unit": "GRM", "value": 1100},
                }
            ],
        },
    }


def test_dimensions_packaging_levels_and_name_conflicts():
    raw = raw_product()
    p = normalize(raw, "authored-test")
    q = quantity(p, Decimal("1000"), "L", True)
    assert q["sales_quantity"] == "1000" and q["sales_unit"] == "ST"
    raw["synkkaData"]["unitConversions"][0]["volume"]["unit"] = "GRM"
    p = normalize(raw, "authored-test")
    assert p["measures"]["L"]["status"] == "unknown"
    assert quantity(p, Decimal("1000"), "L", True)["sales_quantity"] is None
    assert p["measures"]["KG"]["status"] == "unknown"  # gross packaging weight is not food content
    raw["synkkaData"]["unitConversions"][0]["volume"] = {"unit": "LTR", "value": 20}
    assert normalize(raw, "test")["measures"]["L"]["status"] == "conflicting"
    raw["synkkaData"]["unitConversions"][0]["synkkaPackagingType"] = "CASE"
    assert normalize(raw, "test")["measures"]["L"]["status"] == "unknown"


def test_missing_claim_is_unknown_not_dietary_denial():
    p = normalize(raw_product(), "test")
    reasons = requirement_reasons(p, Requirements(lactose_free=True, milk_free=True))
    assert len(reasons) == 2 and all(r["severity"] == "unresolved" for r in reasons)


GROSS_RULES = {
    "currency": "EUR",
    "destinations": ["hotel"],
    "approved_product_ids": [],
    "substitution": "requires_approval",
    "overbuy": "requires_approval",
}
APPROVER_5000 = {"currency": "EUR", "max_gross": "5000", "exceptions": ["overbuy"]}


@pytest.mark.parametrize(
    "total,outcome",
    [
        ("4999.99", "ready_to_commit"),
        ("5000.00", "ready_to_commit"),
        ("5000.01", "needs_resolution"),
    ],
)
def test_gross_boundary(total, outcome):
    """Q-35: the boundary is the approver's maximum, not an autonomous limit."""
    result = evaluate_purchase(
        {"destination": "hotel", "lines": []},
        {"reasons": [], "currency": "EUR", "gross_total": total, "lines": []},
        GROSS_RULES,
        [APPROVER_5000],
    )
    assert result["policy_outcome"] == outcome
    assert "AUTONOMOUS_LIMIT_EXCEEDED" not in {r["code"] for r in result["reasons"]}


@pytest.mark.parametrize(
    "budget,outcome",
    [("100.00", "ready_to_commit"), ("100.01", "ready_to_commit"), ("99.99", "denied")],
)
def test_hard_budget_boundary(budget, outcome):
    result = evaluate_purchase(
        {"destination": "hotel", "lines": [], "budget_gross": budget},
        {"reasons": [], "currency": "EUR", "gross_total": "100.00", "lines": []},
        GROSS_RULES,
        [APPROVER_5000],
    )
    assert result["policy_outcome"] == outcome


def test_unchanged_embeddings_and_failed_import_keep_generation(monkeypatch, agent):
    import aimo.ingest as ingestion

    data = fixture_facts()
    before = publish(data, "test", fingerprint(data))

    def fail(*args):
        raise RuntimeError("injected embedding failure")

    monkeypatch.setattr(ingestion, "embed", fail)
    data[0]["country_of_origin"] = "se"
    reused = publish(data, "metadata-only-test", fingerprint(data))
    assert reused["new_embeddings"] == 0 and reused["reused_embeddings"] == len(data)
    changed = deepcopy(data)
    changed[0]["names"]["en"] = "a new unique search string"
    with pytest.raises(RuntimeError):
        publish(changed, "failed", fingerprint(changed))
    with connection() as c:
        assert (
            str(c.execute("SELECT generation FROM active_catalog").fetchone()["generation"])
            == reused["generation"]
        )
    assert before["model"] == reused["model"]
    assert search_products(agent, SearchRequest(query="464306"))["products"][0]["id"] == "464306"
    publish(fixture_facts(), "authored-test-fixtures", fingerprint(fixture_facts()))


def test_supported_filters_and_conflicts_on_both_search_paths(agent):
    for strategy in ("keyword", "semantic", "hybrid"):
        result = search_products(
            agent,
            SearchRequest(query="milk", requirements=Requirements(lactose_free=True)),
            strategy,
        )
        assert all("FREE_FROM_LACTOSE" in p["claims"] for p in result["products"])
        assert not {"468044", "469429"} & {p["id"] for p in result["products"]}
    assert (
        search_products(
            agent, SearchRequest(query="milk", requirements=Requirements(milk_free=True))
        )["products"]
        == []
    )


def test_missing_currency_is_unresolved():
    result = evaluate_purchase(
        {"destination": "hotel", "lines": []},
        {"reasons": [], "currency": None, "gross_total": None, "lines": []},
        {"currency": "EUR", "destinations": ["hotel"]},
        [],
    )
    assert result["policy_outcome"] == "needs_resolution"


def test_malformed_upstream_has_explicit_failure():
    from aimo.db import Problem

    delivery = date.today() + timedelta(days=2)
    raw = FixtureClient().lookup("123", ["464306"], delivery)
    raw["price"]["products"] = [None]
    with pytest.raises(Problem) as error:
        validate_lookup(raw, "123", ["464306"], delivery, {"464306": fixture_facts()[0]}, now())
    assert error.value.code == "UPSTREAM_SCHEMA_INVALID"
