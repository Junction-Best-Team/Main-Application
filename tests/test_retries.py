from datetime import timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest

from aimo import upstream
from aimo.db import Problem, now


def transport(monkeypatch, handler):
    client_type = httpx.Client
    waits = []
    monkeypatch.setattr(
        upstream,
        "settings",
        lambda: SimpleNamespace(
            valio_aimo_base_url="https://supplier.invalid",
            valio_aimo_api_key="test-only",
        ),
    )
    monkeypatch.setattr(
        upstream.httpx,
        "Client",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    monkeypatch.setattr(upstream.time, "sleep", waits.append)
    monkeypatch.setattr(upstream.random, "uniform", lambda *_: 0)
    return waits


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 501])
def test_permanent_supplier_failures_are_not_retried(monkeypatch, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status)

    waits = transport(monkeypatch, handler)
    with pytest.raises(Problem) as error:
        upstream.ValioClient().post("/api/price", {})
    assert error.value.code == "UPSTREAM_REJECTED"
    assert len(requests) == 1 and waits == []


@pytest.mark.parametrize("first", [408, 429, 500, 502, 503, 504, "connect"])
def test_transient_supplier_failures_back_off_then_succeed(monkeypatch, first):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) < 3:
            if first == "connect":
                raise httpx.ConnectError("test unavailable", request=request)
            return httpx.Response(first)
        return httpx.Response(200, json={"products": []})

    waits = transport(monkeypatch, handler)
    assert upstream.ValioClient().post("/api/price", {}) == {"products": []}
    assert len(requests) == 3 and waits == [0.25, 0.5]


@pytest.mark.parametrize("kind", ["seconds", "date"])
def test_short_retry_after_is_respected(monkeypatch, kind):
    current = now().replace(microsecond=0)
    monkeypatch.setattr(upstream, "now", lambda: current)
    value = (
        "2" if kind == "seconds" else format_datetime(current + timedelta(seconds=2), usegmt=True)
    )
    requests = []

    def handler(request):
        requests.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": value})
            if len(requests) == 1
            else httpx.Response(200, json={})
        )

    waits = transport(monkeypatch, handler)
    assert upstream.ValioClient().post("/api/price", {}) == {}
    assert len(requests) == 2 and waits == [2]


def test_long_retry_after_returns_to_caller_without_retrying_early(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "60"})

    waits = transport(monkeypatch, handler)
    with pytest.raises(Problem) as error:
        upstream.ValioClient().post("/api/price", {})
    assert error.value.code == "UPSTREAM_RATE_LIMITED" and error.value.retry_after == 60
    assert len(requests) == 1 and waits == []


def test_retry_budget_and_invalid_json(monkeypatch):
    requests = []

    def unavailable(request):
        requests.append(request)
        return httpx.Response(503)

    waits = transport(monkeypatch, unavailable)
    with pytest.raises(Problem):
        upstream.ValioClient().post("/api/price", {})
    assert len(requests) == 3 and waits == [0.25, 0.5]


def test_invalid_json_is_not_retried(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=b"not json")

    waits = transport(monkeypatch, handler)
    with pytest.raises(Problem) as error:
        upstream.ValioClient().post("/api/price", {})
    assert error.value.code == "UPSTREAM_SCHEMA_INVALID"
    assert len(requests) == 1 and waits == []
