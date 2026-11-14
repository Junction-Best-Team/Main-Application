"""JNP3-TCT-005 (units on a lookup) and JNP3-SUP-007 (batch merge and setting fallback).

No network: ValioClient is backed by httpx.MockTransport. The Settings field
`supplier_lookup_batch_size` is person 1's; here it is simulated on the class so the getattr
path in upstream.ValioClient.lookup is exercised without editing config.py.
"""

import json
from copy import deepcopy
from datetime import date, timedelta

import httpx
import pytest

from aimo import upstream
from aimo.config import Settings, settings
from aimo.db import Problem, now
from aimo.fixtures import fixture_facts
from aimo.upstream import FixtureClient, ValioClient, validate_lookup

DELIVERY = date(2026, 11, 20)


# ---- TCT-005 -------------------------------------------------------------------------------


def evidence_for(facts, mutation=None, pid="464306"):
    delivery = date.today() + timedelta(days=2)
    raw = FixtureClient().lookup("123", [pid], delivery)
    if mutation:
        mutation(raw)
    return validate_lookup(raw, "123", [pid], delivery, {pid: facts} if facts else {}, now())[pid]


def test_lookup_evidence_states_the_unit_of_quantity_and_price():
    facts = deepcopy(fixture_facts()[0])
    facts.update(sales_unit="KI", base_unit="BOT", units={"ST": "1", "KI": "20"})
    evidence = evidence_for(facts)
    assert evidence["sales_unit"] == "KI"
    assert evidence["base_unit"] == "BOT"
    assert evidence["price_basis"] == "per_sales_unit"
    assert evidence["quantity_unit"] == "KI"
    assert evidence["available_sales_quantity"] is not None and evidence["net"]


def test_lookup_evidence_unit_fields_exist_and_are_null_when_the_catalog_has_no_facts():
    # Deposit materials are priced but not in the product map: the unit is unknown, never guessed.
    evidence = evidence_for(None, pid="demo-deposit")
    assert evidence["sales_unit"] is None and evidence["base_unit"] is None
    assert evidence["quantity_unit"] is None
    assert evidence["available_sales_quantity"] is None
    assert evidence["price_basis"] == "per_sales_unit"


def test_unpriced_lookup_has_no_price_basis():
    evidence = evidence_for(
        deepcopy(fixture_facts()[0]),
        lambda r: r["price"]["products"][0].update(catalogPrice=None),
    )
    assert evidence["net"] is None and evidence["price_basis"] is None
    assert evidence["sales_unit"] == "ST"


def test_existing_keys_are_unchanged():
    evidence = evidence_for(deepcopy(fixture_facts()[0]))
    assert {
        "product_id", "currency", "net", "gross", "tax_rate", "available_sales_quantity",
        "expires_at", "reasons", "mode", "observed_at", "source",
    } <= evidence.keys()  # fmt: skip


# ---- SUP-007 -------------------------------------------------------------------------------


def make_supplier(monkeypatch, handler_rows=None):
    posts = []

    def handler(request):
        body = json.loads(request.content)
        posts.append((request.url.path, body["products"]))
        price = request.url.path == "/api/price"
        out = {
            "customerId": body["customer"],
            "pricingDate" if price else "requestedDate": body["requestedDate"],
            "products": [{"productId": pid} for pid in body["products"]],
        }
        if price:
            out["currency"] = "EUR"
        else:
            out["timeNow"] = "2026-11-14T10:00:00+02:00"
        if handler_rows:
            handler_rows(len(posts), request.url.path, out)
        return httpx.Response(200, json=out)

    real = httpx.Client
    monkeypatch.setattr(
        upstream.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setenv("VALIO_AIMO_API_KEY", "unit-test-key-not-a-real-credential")
    monkeypatch.setenv("VALIO_AIMO_BASE_URL", "https://valio.test")
    settings.cache_clear()
    return posts


@pytest.fixture(autouse=True)
def fresh_settings():
    yield
    settings.cache_clear()


def ids(n):
    return [str(400000 + i) for i in range(n)]


def simulate_setting(monkeypatch, value):
    monkeypatch.setattr(Settings, "supplier_lookup_batch_size", value, raising=False)
    settings.cache_clear()


def sizes(posts, endpoint):
    return [len(b) for p, b in posts if p == endpoint]


@pytest.mark.parametrize("n,expected", [(1000, [1000]), (1001, [1000, 1])])
def test_batch_size_1000_splits_at_the_supplier_limit(monkeypatch, n, expected):
    posts = make_supplier(monkeypatch)
    simulate_setting(monkeypatch, 1000)
    ValioClient().lookup("c", ids(n), DELIVERY)
    assert sizes(posts, "/api/price") == expected
    assert sizes(posts, "/api/availability") == expected


@pytest.mark.parametrize("configured,effective", [(5000, 1000), (0, 1), (-3, 1), ("x", 100)])
def test_out_of_range_setting_is_clamped_to_1_to_1000(monkeypatch, configured, effective):
    posts = make_supplier(monkeypatch)
    simulate_setting(monkeypatch, configured)
    ValioClient().lookup("c", ids(1001), DELIVERY)
    assert max(sizes(posts, "/api/price")) == min(effective, 1000)


def test_without_the_setting_the_module_default_applies(monkeypatch):
    posts = make_supplier(monkeypatch)
    assert upstream.SUPPLIER_LOOKUP_BATCH_SIZE == 100
    ValioClient().lookup("c", ids(250), DELIVERY)
    assert sizes(posts, "/api/price") == [100, 100, 50]


def test_batches_are_sequential_and_price_before_availability_keeps_order(monkeypatch):
    posts = make_supplier(monkeypatch)
    raw = ValioClient().lookup("c", ids(250), DELIVERY)
    assert [p for p, _ in posts] == ["/api/price"] * 3 + ["/api/availability"] * 3
    assert [r["productId"] for r in raw["price"]["products"]] == ids(250)
    assert [r["productId"] for r in raw["availability"]["products"]] == ids(250)


def test_merged_envelope_keeps_the_fields_validate_lookup_reads(monkeypatch):
    make_supplier(monkeypatch)
    raw = ValioClient().lookup("c", ids(250), DELIVERY)
    assert raw["price"]["customerId"] == "c" and raw["price"]["currency"] == "EUR"
    assert raw["price"]["pricingDate"] == "2026-11-20"
    assert raw["availability"]["requestedDate"] == "2026-11-20"
    assert raw["availability"]["timeNow"]


@pytest.mark.parametrize(
    "path,field,value",
    [
        ("/api/price", "customerId", "someone-else"),
        ("/api/price", "currency", "USD"),
        ("/api/price", "pricingDate", "2026-11-21"),
        ("/api/availability", "customerId", "someone-else"),
        ("/api/availability", "requestedDate", "2026-11-21"),
    ],
)
def test_batches_that_disagree_on_context_are_not_merged(monkeypatch, path, field, value):
    def rows(call_number, path_, out):
        later_batch = out["products"][0]["productId"] != ids(1)[0]
        if later_batch and path_ == path:
            out[field] = value

    make_supplier(monkeypatch, rows)
    with pytest.raises(Problem) as caught:
        ValioClient().lookup("c", ids(250), DELIVERY)
    assert caught.value.code == "UPSTREAM_SCHEMA_INVALID"


def test_a_malformed_batch_envelope_is_a_schema_problem(monkeypatch):
    def rows(call_number, path_, out):
        out["products"] = "not-a-list"

    make_supplier(monkeypatch, rows)
    with pytest.raises(Problem) as caught:
        ValioClient().lookup("c", ids(250), DELIVERY)
    assert caught.value.code == "UPSTREAM_SCHEMA_INVALID"
