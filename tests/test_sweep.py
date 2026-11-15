"""Regression checks for sweep side effects and honest live-supplier verification."""

import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from supplier_fixture import FixtureClient
from sweep.check_live import check_live
from sweep.run_sweep import Sweep

from aimo import upstream
from aimo.api import create_app
from aimo.config import settings
from aimo.db import Problem

DELIVERY = date.today() + timedelta(days=2)


def test_standalone_sweep_never_invokes_a_configured_provider(monkeypatch):
    monkeypatch.setattr(settings(), "llm_api_key", "fake-configured-provider")
    app = create_app()
    app.state.agent_runner = lambda *args: pytest.fail("sweep invoked the provider")
    with TestClient(app) as client:
        sweep = Sweep("http://testserver", "test-buyer-password-only")
        sweep.http.close()
        sweep.http = client
        sweep.login()
        sweep.conversation_create_and_retry()
        sweep.run("message CSRF enforced", sweep.message_csrf_enforced)
        assert sweep.results[0][1] == "PASS", sweep.results
        detail = client.get(f"/api/conversations/{sweep.conversation}").json()
        assert detail["messages"] == []


def supplier(monkeypatch, *, status=200, defect=None):
    monkeypatch.setattr(settings(), "valio_aimo_api_key", "fake-supplier-key")
    requests = []

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.headers["X-API-Key"] == "fake-supplier-key"
        assert body["products"] == ["463380"]
        raw = FixtureClient().lookup(body["customer"], body["products"], DELIVERY)
        if defect:
            defect(raw)
        field = "price" if request.url.path == "/api/price" else "availability"
        return httpx.Response(status, json=raw[field])

    real_client = httpx.Client
    monkeypatch.setattr(
        upstream.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    return requests


def test_live_probe_queries_both_supplier_endpoints_even_in_fixture_mode(monkeypatch):
    requests = supplier(monkeypatch)
    assert settings().upstream_mode == "fixture"
    assert check_live("463380", DELIVERY).startswith("PASS live supplier")
    assert [request.url.path for request in requests] == ["/api/price", "/api/availability"]


def test_live_probe_refuses_missing_credentials_before_network(monkeypatch):
    requests = supplier(monkeypatch)
    monkeypatch.setattr(settings(), "valio_aimo_api_key", "")
    with pytest.raises(Problem, match="VALIO_AIMO_API_KEY"):
        check_live("463380", DELIVERY)
    assert requests == []


def test_live_probe_propagates_supplier_rejection(monkeypatch):
    supplier(monkeypatch, status=403)
    with pytest.raises(Problem) as error:
        check_live("463380", DELIVERY)
    assert error.value.code == "UPSTREAM_REJECTED"


@pytest.mark.parametrize("field", ["price", "availability"])
def test_live_probe_rejects_missing_commercial_evidence(monkeypatch, field):
    supplier(monkeypatch, defect=lambda raw: raw[field].update(products=[]))
    with pytest.raises(Problem) as error:
        check_live("463380", DELIVERY)
    assert error.value.code == "LIVE_EVIDENCE_UNRESOLVED"


def test_live_probe_rejects_unknown_stock(monkeypatch):
    def unknown(raw):
        raw["availability"]["products"][0]["scheduleLines"][0]["availableAmount"] = "9999999999"

    supplier(monkeypatch, defect=unknown)
    with pytest.raises(Problem) as error:
        check_live("463380", DELIVERY)
    assert "UNVERIFIED_STOCK" in error.value.message


def test_live_ci_without_key_exits_before_starting_server():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", "tests/ci.sh", "--live", "--skip-unit"],
        cwd=root,
        env={
            **os.environ,
            "CI": "1",
            "UV_NO_SYNC": "1",
            "CI_COVERAGE": "0",
            "VALIO_AIMO_API_KEY": "",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "UPSTREAM_CREDENTIALS_MISSING" in result.stderr
    assert "Start server" not in result.stdout
    assert "ALL CI STEPS PASSED" not in result.stdout
