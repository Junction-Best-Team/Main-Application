"""Q-72: the interactive documentation and the OpenAPI document are not served unless asked for.

A hosted deployment does not publish its API surface. `API_DOCS_ENABLED=true` turns /docs and
/openapi.json on for local development. The contract file the typed client is built from is
generated from the app object (`scripts/export_schema.py`), not from the served route, so it is
unaffected. Local app only.
"""

import pytest
from fastapi.testclient import TestClient

from aimo.api import create_app
from aimo.config import settings

HIDDEN = ["/docs", "/redoc", "/openapi.json"]


@pytest.fixture
def hidden(service):
    with TestClient(create_app(service)) as client:
        yield client


@pytest.mark.parametrize("path", HIDDEN)
def test_documentation_routes_are_not_served_by_default(hidden, path):
    response = hidden.get(path)
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not found."}}


@pytest.mark.parametrize("path", HIDDEN)
def test_hidden_documentation_routes_keep_the_security_headers(hidden, path):
    headers = hidden.get(path).headers
    assert headers["x-content-type-options"] == "nosniff" and headers["x-frame-options"] == "DENY"
    assert "script-src 'self';" in headers["content-security-policy"]


def test_the_default_is_off(monkeypatch):
    assert settings().api_docs_enabled is False


def test_the_contract_is_still_generated_from_the_app_object(service):
    spec = create_app(service).openapi()
    assert "/api/login" in spec["paths"] and "/api/purchases/{proposal_id}/confirm" in spec["paths"]
    assert not {"/docs", "/redoc", "/openapi.json"} & set(spec["paths"])


def test_the_enabled_setting_serves_the_docs_and_the_spec(service, monkeypatch):
    monkeypatch.setattr(settings(), "api_docs_enabled", True)
    with TestClient(create_app(service)) as client:
        assert client.get("/docs").status_code == 200
        spec = client.get("/openapi.json")
        assert spec.status_code == 200 and "/api/login" in spec.json()["paths"]
        assert client.get("/redoc").status_code == 404  # ReDoc is never served
