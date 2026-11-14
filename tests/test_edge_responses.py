"""Smaller response-level fixes found by the read-only smoke test of the deployed app.

- an unknown route or a wrong method answers in the application's own error shape, not FastAPI's
  default {"detail": "Not Found"};
- the health routes answer HEAD as well as GET (an external monitor often probes with HEAD);
- HTTPS deployments (SECURE_COOKIES on) send Strict-Transport-Security; local HTTP does not.
Local app only.
"""

import pytest
from fastapi.testclient import TestClient

from aimo.api import create_app
from aimo.config import settings


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as c:
        yield c


def error_of(response):
    body = response.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message"}, body
    return body["error"]


@pytest.mark.parametrize("path", ["/api/nonexistent", "/mcp", "/api/agent/tools", "/nowhere"])
def test_an_unknown_route_uses_the_application_error_shape(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert error_of(response)["code"] == "NOT_FOUND"


@pytest.mark.parametrize("path", ["/api/login", "/api/logout"])
def test_a_wrong_method_uses_the_application_error_shape_and_keeps_allow(client, path):
    response = client.get(path)
    assert response.status_code == 405
    assert error_of(response)["code"] == "METHOD_NOT_ALLOWED"
    assert response.headers["allow"] == "POST"


def test_an_error_raised_by_a_route_keeps_its_own_code(client):
    response = client.get("/api/conversations")
    assert response.status_code == 401 and error_of(response)["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_health_routes_answer_head_with_the_same_status_as_get(client, path):
    get, head = client.get(path), client.head(path)
    assert head.status_code == get.status_code == 200
    assert head.content == b""


def test_the_health_head_routes_are_not_added_to_the_published_contract(client):
    paths = client.app.openapi()["paths"]
    assert "head" not in paths["/health/live"] and "head" not in paths["/health/ready"]


def test_hsts_is_sent_only_when_the_deployment_is_https(service, monkeypatch):
    monkeypatch.setattr(settings(), "secure_cookies", True)
    with TestClient(create_app(service)) as client:
        assert client.get("/health/live").headers["strict-transport-security"] == "max-age=31536000"
        assert client.get("/api/session").headers["strict-transport-security"] == "max-age=31536000"
    monkeypatch.setattr(settings(), "secure_cookies", False)
    with TestClient(create_app(service)) as client:
        assert "strict-transport-security" not in client.get("/health/live").headers
