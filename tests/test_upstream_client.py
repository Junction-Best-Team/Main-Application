"""The live Valio HTTP client (retries, fail-closed errors) and supplier-response validation.

No real network: httpx.Client is replaced by one backed by httpx.MockTransport, and time.sleep is
recorded instead of waiting.
"""

import json
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from aimo import upstream
from aimo.config import Settings
from aimo.db import Problem, now
from aimo.fixtures import fixture_facts
from aimo.upstream import FixtureClient, ValioClient, validate_lookup

KEY = "unit-test-key-not-a-real-credential"


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(upstream.time, "sleep", recorded.append)
    return recorded


def serve(monkeypatch, handler, key=KEY):
    cfg = Settings(
        _env_file=None,
        upstream_mode="live",
        valio_aimo_api_key=key,
        valio_aimo_base_url="https://valio.test",
    )
    monkeypatch.setattr(upstream, "settings", lambda: cfg)
    real = httpx.Client
    monkeypatch.setattr(
        upstream.httpx,
        "Client",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


# --- ValioClient.post ----------------------------------------------------------------------------


def test_post_sends_key_and_json_and_does_not_follow_redirects(monkeypatch, sleeps):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    serve(monkeypatch, handler)
    assert ValioClient().post("/api/price", {"products": ["1"]}) == {"ok": True}
    request = seen[0]
    assert str(request.url) == "https://valio.test/api/price"
    assert request.headers["x-api-key"] == KEY
    assert request.headers["user-agent"].startswith("Junction-Aimo-Gateway/")
    assert json.loads(request.content) == {"products": ["1"]}
    assert sleeps == []


def test_post_retries_429_with_exponential_backoff_then_succeeds(monkeypatch, sleeps):
    answers = iter([429, 429, 200])

    def handler(request):
        code = next(answers)
        return httpx.Response(code, json={"attempt": "last"} if code == 200 else {})

    serve(monkeypatch, handler)
    assert ValioClient().post("/api/price", {}) == {"attempt": "last"}
    assert sleeps == [0.25, 0.5]


def test_post_retries_a_server_error_then_succeeds(monkeypatch, sleeps):
    answers = iter([503, 200])
    serve(
        monkeypatch,
        lambda r: httpx.Response(next(answers), json={"v": 1}),
    )
    assert ValioClient().post("/api/price", {}) == {"v": 1}
    assert sleeps == [0.25]


def test_post_retries_a_transport_error_then_succeeds(monkeypatch, sleeps):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"v": 2})

    serve(monkeypatch, handler)
    assert ValioClient().post("/api/price", {}) == {"v": 2}
    assert len(calls) == 2


@pytest.mark.parametrize("status", [429, 500, 502, 504])
def test_post_exhausted_retries_fail_closed_without_leaking_the_key(monkeypatch, sleeps, status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, text=f"upstream said no, key was {KEY}")

    serve(monkeypatch, handler)
    with pytest.raises(Problem) as error:
        ValioClient().post("/api/price", {})
    assert (error.value.code, error.value.status) == ("UPSTREAM_UNAVAILABLE", 503)
    assert "no commercial terms were confirmed" in error.value.message
    assert KEY not in error.value.message
    assert len(calls) == 3
    assert sleeps == [0.25, 0.5]


def test_post_client_error_is_reported_as_unavailable(monkeypatch, sleeps):
    serve(monkeypatch, lambda r: httpx.Response(401, json={"detail": "bad key"}))
    with pytest.raises(Problem) as error:
        ValioClient().post("/api/price", {})
    assert error.value.code == "UPSTREAM_UNAVAILABLE"


def test_post_a_redirect_is_not_followed_and_is_an_error(monkeypatch, sleeps):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://elsewhere.test/steal"})

    serve(monkeypatch, handler)
    with pytest.raises(Problem) as error:
        ValioClient().post("/api/price", {})
    assert error.value.code == "UPSTREAM_UNAVAILABLE"
    assert all(url.startswith("https://valio.test/") for url in seen)


def test_post_malformed_json_body_fails_closed(monkeypatch, sleeps):
    serve(monkeypatch, lambda r: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(Problem) as error:
        ValioClient().post("/api/price", {})
    assert error.value.code == "UPSTREAM_UNAVAILABLE"


def test_post_without_a_key_makes_no_request(monkeypatch):
    serve(monkeypatch, lambda r: pytest.fail("must not call upstream without a key"), key="")
    with pytest.raises(Problem) as error:
        ValioClient().post("/api/price", {})
    assert (error.value.code, error.value.status) == ("UPSTREAM_CREDENTIALS_MISSING", 503)


def test_lookup_posts_price_then_availability_and_labels_the_result_live(monkeypatch, sleeps):
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"echo": request.url.path})

    serve(monkeypatch, handler)
    delivery = date(2030, 5, 6)
    result = ValioClient().lookup("123", ["464306", "464398"], delivery)
    payload = {"customer": "123", "requestedDate": "2030-05-06", "products": ["464306", "464398"]}
    assert seen == [("/api/price", payload), ("/api/availability", payload)]
    assert result["mode"] == "live"
    assert result["price"] == {"echo": "/api/price"}
    assert result["availability"] == {"echo": "/api/availability"}
    assert result["observed_at"]


# --- validate_lookup -----------------------------------------------------------------------------

DELIVERY = date.today() + timedelta(days=2)


def check(mutation, products=None, ids=("464306",)):
    raw = FixtureClient().lookup("123", list(ids), DELIVERY)
    mutation(raw)
    facts = products if products is not None else {p["id"]: p for p in fixture_facts()}
    return validate_lookup(raw, "123", list(ids), DELIVERY, facts, now())


def price(raw):
    return raw["price"]["products"][0]


def avail(raw):
    return raw["availability"]["products"][0]


def codes(result, pid="464306"):
    return {r["code"] for r in result[pid]["reasons"]}


def test_clean_fixture_response_is_fully_resolved():
    result = check(lambda raw: None)["464306"]
    assert result["reasons"] == []
    assert result["net"] == "1.50" and result["gross"] == "1.70"
    assert Decimal(result["tax_rate"]) == Decimal("13.5")
    assert Decimal(result["available_sales_quantity"]) == 600
    assert result["mode"] == "fixture"


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda r: r["availability"].update(timeNow="2001-01-01T00:00:00Z"),
            "UPSTREAM_CLOCK_STALE",
        ),
        (lambda r: r["availability"].pop("timeNow"), "UPSTREAM_CLOCK_UNKNOWN"),
        (lambda r: r["availability"].update(timeNow="not a time"), "UPSTREAM_CLOCK_UNKNOWN"),
        (
            lambda r: r["availability"].update(requestedDate="2001-01-01"),
            "UPSTREAM_CONTEXT_MISMATCH",
        ),
        (lambda r: r["price"].update(pricingDate="2001-01-01"), "UPSTREAM_CONTEXT_MISMATCH"),
        (lambda r: r["availability"].update(products=[]), "UPSTREAM_PRODUCT_MISMATCH"),
        (lambda r: price(r).update(error=True), "MISSING_PRICE"),
        (lambda r: price(r).update(quantity=2), "MISSING_PRICE"),
        (lambda r: r["price"].update(currency="SEK"), "MISSING_PRICE"),
        (lambda r: price(r)["catalogPrice"].update(currency="USD"), "MISSING_PRICE"),
        (lambda r: price(r)["priceWithTax"].update(currency="USD"), "MISSING_PRICE"),
        (lambda r: price(r)["catalogPrice"].update(value="-1"), "MISSING_PRICE"),
        (lambda r: price(r)["catalogPrice"].update(value="NaN"), "MISSING_PRICE"),
        (lambda r: price(r)["tax"].update(taxRate="101"), "MISSING_PRICE"),
        (lambda r: price(r)["catalogPrice"].update(valueWithTax="9.99"), "MISSING_PRICE"),
        (lambda r: price(r)["tax"].update(taxValue="9.99"), "MISSING_PRICE"),
        (lambda r: price(r)["priceWithTax"].update(value="not-a-number"), "MISSING_PRICE"),
        (
            lambda r: price(r)["priceWithTax"].update(validFrom="2999-01-01"),
            "PRICE_OUTSIDE_VALIDITY",
        ),
        (lambda r: avail(r).update(salesBlock=True), "SALES_BLOCK"),
        (lambda r: avail(r).update(salesBlock=None), "SALES_BLOCK"),
        (lambda r: avail(r)["scheduleLines"].append({}), "DELIVERY_UNRESOLVED"),
        (
            lambda r: avail(r)["scheduleLines"][0].update(availableAmount="-1"),
            "DELIVERY_UNRESOLVED",
        ),
        (
            lambda r: avail(r)["scheduleLines"][0].update(availableAmount="NaN"),
            "DELIVERY_UNRESOLVED",
        ),
        (lambda r: avail(r)["scheduleLines"][0].pop("availableDate"), "DELIVERY_UNRESOLVED"),
        (lambda r: avail(r).pop("closingTime"), "DELIVERY_UNRESOLVED"),
    ],
)
def test_supplier_defects_become_unresolved_reasons(mutation, code):
    result = check(mutation)
    assert code in codes(result)
    assert all(r["severity"] == "unresolved" for r in result["464306"]["reasons"])


def test_unusable_price_leaves_price_unknown_not_zero():
    result = check(lambda r: price(r)["catalogPrice"].update(value="-1"))["464306"]
    assert result["net"] is None and result["gross"] is None and result["tax_rate"] is None


def test_unverified_or_blocked_stock_leaves_quantity_unknown_not_zero():
    result = check(lambda r: avail(r).update(logisticModel="Terminal"))["464306"]
    assert result["available_sales_quantity"] is None
    assert "UNVERIFIED_STOCK" in codes({"464306": result})


def test_zero_unit_factor_is_unresolved_instead_of_dividing():
    products = {"464306": deepcopy(fixture_facts()[0])}
    products["464306"]["units"] = {"ST": "0", "KI": "20"}
    result = check(lambda r: None, products=products)["464306"]
    assert "DELIVERY_UNRESOLVED" in codes({"464306": result})
    assert result["available_sales_quantity"] is None


def test_zero_factor_for_the_reported_unit_is_unresolved():
    products = {"464306": deepcopy(fixture_facts()[0])}
    products["464306"]["units"] = {"ST": "1", "KI": "0"}
    result = check(
        lambda r: avail(r)["scheduleLines"][0].update(salesUnit="KI"), products=products
    )["464306"]
    assert "DELIVERY_UNRESOLVED" in codes({"464306": result})
    assert result["available_sales_quantity"] is None


def test_price_only_lines_need_no_fulfilment_schedule():
    """Deposit materials are priced but not in the product map: no availability is required."""
    result = check(lambda r: avail(r).update(scheduleLines=[]), products={})["464306"]
    assert result["reasons"] == []
    assert result["gross"] == "1.70" and result["available_sales_quantity"] is None


def test_price_validity_end_caps_the_proposal_expiry(monkeypatch):
    cfg = Settings(_env_file=None, proposal_ttl_seconds=30 * 86400)  # TTL far beyond the price
    monkeypatch.setattr(upstream, "settings", lambda: cfg)
    last_day = DELIVERY.isoformat()  # still valid on the delivery date, not after it
    late_cutoff = f"{DELIVERY + timedelta(days=5)}T17:00:00+02:00"

    def mutate(raw):
        price(raw)["catalogPrice"].update(validTo=last_day)
        price(raw)["priceWithTax"].update(validTo=last_day)
        avail(raw).update(closingTime=late_cutoff)

    result = check(mutate)["464306"]
    assert result["reasons"] == []
    assert result["expires_at"].startswith(last_day)
