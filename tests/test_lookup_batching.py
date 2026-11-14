"""JNP3-SUP-007 (Draft): a price and availability lookup is split into batches within the supplier's
per-request limit.

The supplier accepts 1 to 1000 product ids per request (`ProductsRequest.products`, minItems 1,
maxItems 1000 in docs/reference/aimo-api.openapi.json). The owner's answer: the batch size is the
setting `supplier_lookup_batch_size` (env SUPPLIER_LOOKUP_BATCH_SIZE), default 100, validated 1..1000.

No network: httpx.Client is backed by httpx.MockTransport. Every test that is not the control is a
strict xfail, so it turns into an error (XPASS) the moment the batching is built.
"""

import json
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from aimo import upstream
from aimo.config import Settings, settings
from aimo.upstream import ValioClient

DELIVERY = date(2026, 11, 20)
ENDPOINTS = ("/api/price", "/api/availability")


@pytest.fixture
def supplier(monkeypatch):
    """Record every POST to the mocked supplier; echo a response row for each requested id."""
    posts = []

    def handler(request):
        body = json.loads(request.content)
        posts.append((request.url.path, body["products"]))
        key = "pricingDate" if request.url.path == "/api/price" else "requestedDate"
        return httpx.Response(
            200,
            json={
                "customerId": body["customer"],
                key: body["requestedDate"],
                "products": [{"productId": pid} for pid in body["products"]],
            },
        )

    real = httpx.Client
    monkeypatch.setattr(
        upstream.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setenv("VALIO_AIMO_API_KEY", "unit-test-key-not-a-real-credential")
    monkeypatch.setenv("VALIO_AIMO_BASE_URL", "https://valio.test")
    monkeypatch.delenv("SUPPLIER_LOOKUP_BATCH_SIZE", raising=False)
    settings.cache_clear()

    def configure(batch_size=None):
        if batch_size is not None:
            monkeypatch.setenv("SUPPLIER_LOOKUP_BATCH_SIZE", str(batch_size))
        settings.cache_clear()

    yield posts, configure
    monkeypatch.undo()
    settings.cache_clear()


def ids(n):
    return [f"{400000 + i}" for i in range(n)]


def lookup(requested):
    return ValioClient().lookup("customer-1", requested, DELIVERY)


def sent(posts, endpoint):
    return [batch for path, batch in posts if path == endpoint]


def test_control_a_short_lookup_is_one_request_per_endpoint_carrying_every_id(supplier):
    """Control (passes today): the mock records one POST per endpoint with all ids and echoes them."""
    posts, configure = supplier
    configure()
    requested = ids(3)
    raw = lookup(requested)
    assert [path for path, _ in posts] == list(ENDPOINTS)
    assert all(batch == requested for _, batch in posts)
    assert [p["productId"] for p in raw["price"]["products"]] == requested
    assert [p["productId"] for p in raw["availability"]["products"]] == requested


def test_every_request_stays_within_the_configured_batch_size(supplier):
    """JNP3-SUP-007 (a): with SUPPLIER_LOOKUP_BATCH_SIZE=250, each POST to /api/price and
    /api/availability carries at most min(250, 1000) ids when 1500 are requested."""
    posts, configure = supplier
    configure(250)
    lookup(ids(1500))
    for endpoint in ENDPOINTS:
        batches = sent(posts, endpoint)
        assert batches, f"no request reached {endpoint}"
        assert max(len(batch) for batch in batches) <= 250, [len(b) for b in batches]


def test_the_default_batch_size_is_100_and_never_exceeds_the_supplier_limit(supplier):
    """JNP3-SUP-007 (a)+(d): without any setting, 1500 ids go out in 15 requests of at most 100 per
    endpoint, and no request ever exceeds the supplier's 1000-id limit."""
    posts, configure = supplier
    configure()
    lookup(ids(1500))
    for endpoint in ENDPOINTS:
        sizes = [len(batch) for batch in sent(posts, endpoint)]
        assert sizes and max(sizes) <= 100, sizes
        assert len(sizes) == 15, sizes


def test_the_batches_are_exactly_the_requested_ids_in_order_without_duplicates(supplier):
    """JNP3-SUP-007 (b): for each endpoint the batches, in sequence, equal the requested ids (same
    order, no id twice, none missing), and the merged response still covers every id."""
    posts, configure = supplier
    configure(250)
    requested = ids(1500)
    raw = lookup(requested)
    for endpoint in ENDPOINTS:
        batches = sent(posts, endpoint)
        assert len(batches) > 1, "the 1500 ids were not split"
        flat = [pid for batch in batches for pid in batch]
        assert flat == requested  # union equals request, order kept
        assert len(set(flat)) == len(flat)  # no duplicates
    assert [p["productId"] for p in raw["price"]["products"]] == requested
    assert [p["productId"] for p in raw["availability"]["products"]] == requested


@pytest.mark.xfail(
    strict=True,
    reason="waiting for person 1: add supplier_lookup_batch_size to config.py",
)
def test_with_batch_size_1000_exactly_1000_ids_is_one_call_and_1001_is_two(supplier):
    """JNP3-SUP-007 (c): with the batch size set to 1000, 1000 ids make one POST per endpoint and
    1001 ids make two (1000 + 1)."""
    posts, configure = supplier
    configure(1000)
    lookup(ids(1000))
    assert [len(sent(posts, e)) for e in ENDPOINTS] == [1, 1]  # holds today as well
    posts.clear()
    lookup(ids(1001))
    for endpoint in ENDPOINTS:
        sizes = [len(batch) for batch in sent(posts, endpoint)]
        assert sizes == [1000, 1], sizes


@pytest.mark.xfail(
    strict=True,
    reason="waiting for person 1: add supplier_lookup_batch_size to config.py",
)
def test_the_batch_size_is_a_setting_with_default_100(monkeypatch):
    """JNP3-SUP-007 (d): Settings has `supplier_lookup_batch_size`, default 100, read from
    SUPPLIER_LOOKUP_BATCH_SIZE."""
    monkeypatch.delenv("SUPPLIER_LOOKUP_BATCH_SIZE", raising=False)
    assert "supplier_lookup_batch_size" in Settings.model_fields
    assert Settings(_env_file=None).supplier_lookup_batch_size == 100
    monkeypatch.setenv("SUPPLIER_LOOKUP_BATCH_SIZE", "37")
    assert Settings(_env_file=None).supplier_lookup_batch_size == 37


@pytest.mark.xfail(
    strict=True,
    reason="waiting for person 1: add supplier_lookup_batch_size to config.py",
)
@pytest.mark.parametrize("value", [1, 1000])
def test_the_batch_size_accepts_the_supplier_limits(value, monkeypatch):
    """JNP3-SUP-007 (d): 1 and 1000 are valid values of supplier_lookup_batch_size."""
    monkeypatch.delenv("SUPPLIER_LOOKUP_BATCH_SIZE", raising=False)
    assert "supplier_lookup_batch_size" in Settings.model_fields
    assert Settings(
        _env_file=None, supplier_lookup_batch_size=value
    ).supplier_lookup_batch_size == (value)


@pytest.mark.xfail(
    strict=True,
    reason="waiting for person 1: add supplier_lookup_batch_size to config.py",
)
@pytest.mark.parametrize("value", [0, 1001])
def test_the_batch_size_outside_1_to_1000_is_rejected(value, monkeypatch):
    """JNP3-SUP-007 (d): 0 and 1001 raise a validation error (supplier accepts 1 to 1000 ids)."""
    monkeypatch.delenv("SUPPLIER_LOOKUP_BATCH_SIZE", raising=False)
    assert "supplier_lookup_batch_size" in Settings.model_fields
    with pytest.raises(ValidationError):
        Settings(_env_file=None, supplier_lookup_batch_size=value)
