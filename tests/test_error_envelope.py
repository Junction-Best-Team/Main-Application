"""TCT-008 (owner decision Q-73): every HTTP error is {"error": {"code", "message", "details"?}}.

Covers validation errors, malformed JSON, unknown routes, wrong methods, application `Problem`
errors, plain HTTPExceptions, an unhandled exception, the OpenAPI declaration and drift between
the committed frontend/openapi.json and what the app generates. Local app only.
"""

import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aimo.api import create_app
from aimo.db import Problem

SECRET = "hunter2-do-not-echo"
ORIGIN = {"Origin": "http://testserver"}


def envelope(response, status, code=None):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}, body
    error = body["error"]
    assert set(error) <= {"code", "message", "details"}, error
    assert isinstance(error["code"], str) and error["code"] == error["code"].upper()
    assert isinstance(error["message"], str) and error["message"]
    walk_no_input_or_ctx(error)
    if code:
        assert error["code"] == code, error
    return error


def walk_no_input_or_ctx(value):
    if isinstance(value, dict):
        assert "input" not in value and "ctx" not in value, value
        for item in value.values():
            walk_no_input_or_ctx(item)
    elif isinstance(value, list):
        for item in value:
            walk_no_input_or_ctx(item)


@pytest.fixture
def app(service):
    app = create_app(service)

    @app.get("/test/problem")
    def problem():
        raise Problem("RATE_LIMITED", "Slow down.", 429, retry_after=7)

    @app.get("/test/forbidden")
    def forbidden():
        raise HTTPException(403, "Not yours.")

    @app.get("/test/conflict")
    def conflict():
        raise HTTPException(409, "Already there.", headers={"X-Probe": "1"})

    @app.get("/test/unauthorized")
    def unauthorized():
        raise HTTPException(401, "Sign in.", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/test/structured")
    def structured():
        raise HTTPException(400, {"password": SECRET})

    @app.get("/test/too-large")
    def too_large():
        raise HTTPException(413)

    @app.get("/test/teapot")
    def teapot():
        raise HTTPException(418, "short and stout")

    @app.get("/test/boom")
    def boom():
        raise RuntimeError("private database URL " + SECRET)

    return app


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_a_validation_error_is_an_envelope_with_details_and_no_submitted_values(client):
    response = client.post(
        "/api/login", headers=ORIGIN, json={"username": "buyer", "password": [SECRET]}
    )
    error = envelope(response, 422, "VALIDATION_ERROR")
    assert SECRET not in response.text
    assert "password" in error["message"]
    assert error["details"][0]["loc"] == ["body", "password"]
    assert error["details"][0]["type"] == "string_type"
    for item in error["details"]:
        assert set(item) == {"type", "loc", "msg"}


def test_a_missing_field_names_the_field_and_does_not_echo_the_rest_of_the_body(client):
    response = client.post("/api/login", headers=ORIGIN, json={"username": SECRET})
    error = envelope(response, 422, "VALIDATION_ERROR")
    assert SECRET not in response.text
    assert error["message"] == "password is required."
    assert error["details"] == [
        {"type": "missing", "loc": ["body", "password"], "msg": "Field required"}
    ]


def test_several_errors_summarise_the_first_and_list_all_in_details(client):
    response = client.post("/api/login", headers=ORIGIN, json={})
    error = envelope(response, 422, "VALIDATION_ERROR")
    assert len(error["details"]) == 2 and "(and 1 more)" in error["message"]


def signed_in(client):
    login = client.post(
        "/api/login",
        headers=ORIGIN,
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert login.status_code == 200
    return login


def test_a_query_error_names_the_query_parameter(client):
    signed_in(client)
    error = envelope(client.get("/api/approvals?limit=500"), 422, "VALIDATION_ERROR")
    assert error["message"].startswith("limit ")
    assert error["details"][0]["loc"] == ["query", "limit"]


def test_a_malformed_json_body_is_an_envelope_and_not_echoed(client):
    response = client.post(
        "/api/login",
        headers=ORIGIN | {"Content-Type": "application/json"},
        content='{"username": "' + SECRET + '", ',
    )
    error = envelope(response, 422, "VALIDATION_ERROR")
    assert SECRET not in response.text
    assert "JSON" in error["message"]


def test_a_non_uuid_path_parameter_is_an_envelope(client):
    signed_in(client)
    response = client.get("/api/purchases/" + SECRET)
    envelope(response, 422, "VALIDATION_ERROR")
    assert SECRET not in response.text


def test_an_unknown_route_is_not_found(client):
    envelope(client.get("/api/nonexistent"), 404, "NOT_FOUND")


def test_a_wrong_method_is_method_not_allowed_and_keeps_allow(client):
    response = client.get("/api/login")
    envelope(response, 405, "METHOD_NOT_ALLOWED")
    assert response.headers["allow"] == "POST"


def test_a_missing_session_is_a_401_envelope(client):
    envelope(client.get("/api/session"), 401, "UNAUTHENTICATED")


def test_a_csrf_or_origin_failure_is_a_403_envelope(client):
    login = client.post(
        "/api/login",
        headers=ORIGIN,
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert login.status_code == 200
    response = client.post("/api/logout", headers=ORIGIN)  # no CSRF token
    assert response.status_code == 403
    envelope(response, 403)


def test_a_problem_keeps_its_code_and_retry_after(client):
    response = client.get("/test/problem")
    error = envelope(response, 429, "RATE_LIMITED")
    assert error["message"] == "Slow down."
    assert response.headers["retry-after"] == "7"


def test_a_problem_with_structured_details_keeps_them(client, monkeypatch):
    from aimo.basket_errors import BasketProblem

    app = client.app

    @app.get("/test/basket")
    def basket():
        raise BasketProblem("MEAL_BASKET_MISMATCH", "Fix the lines.", {"missing": ["milk"]})

    error = envelope(client.get("/test/basket"), 422, "MEAL_BASKET_MISMATCH")
    assert error["details"] == {"missing": ["milk"]}


@pytest.mark.parametrize(
    "path,status,code,message",
    [
        ("/test/unauthorized", 401, "UNAUTHORIZED", "Sign in."),
        ("/test/forbidden", 403, "FORBIDDEN", "Not yours."),
        ("/test/conflict", 409, "CONFLICT", "Already there."),
        ("/test/too-large", 413, "PAYLOAD_TOO_LARGE", "Request body too large."),
        ("/test/teapot", 418, "IM_A_TEAPOT", "short and stout"),
    ],
)
def test_other_http_exceptions_use_a_status_code_and_their_text(
    client, path, status, code, message
):
    error = envelope(client.get(path), status, code)
    assert error["message"] == message


def test_http_exception_headers_are_preserved(client):
    assert client.get("/test/conflict").headers["x-probe"] == "1"
    assert client.get("/test/unauthorized").headers["www-authenticate"] == "Bearer"


def test_a_non_string_http_exception_detail_is_not_exposed(client):
    response = client.get("/test/structured")
    error = envelope(response, 400, "BAD_REQUEST")
    assert SECRET not in response.text
    assert error["message"] == "The request could not be processed."


def test_an_unhandled_exception_is_a_generic_500_without_internals(client):
    response = client.get("/test/boom")
    error = envelope(response, 500, "INTERNAL_ERROR")
    assert error["message"] == "The service hit an unexpected error. Try again."
    for leaked in ("private database URL", SECRET, "Traceback", "RuntimeError", "boom"):
        assert leaked not in response.text


def test_204_and_sse_are_unaffected(client):
    login = client.post(
        "/api/login",
        headers=ORIGIN,
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    out = client.post("/api/logout", headers=ORIGIN | {"X-CSRF-Token": login.json()["csrf_token"]})
    assert out.status_code == 204 and out.content == b""
    # An unauthenticated SSE request fails before streaming starts, with the envelope.
    envelope(client.get("/api/conversations/00000000-0000-0000-0000-000000000000/events"), 401)


def _operations(document):
    for path, item in document["paths"].items():
        for method, operation in item.items():
            yield path, method, operation


def test_openapi_declares_the_envelope_and_no_http_validation_error(service):
    document = create_app(service).openapi()
    assert "HTTPValidationError" not in json.dumps(document)
    assert "ValidationError" not in document["components"]["schemas"]
    for name in ("ErrorResponse", "ErrorBody", "ErrorDetail"):
        assert name in document["components"]["schemas"]
    ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, method, operation in _operations(document):
        responses = operation["responses"]
        for key in ("4XX", "5XX"):
            assert responses[key]["content"]["application/json"]["schema"] == ref, (path, key)
        takes_input = operation.get("parameters") or operation.get("requestBody")
        assert ("422" in responses) == bool(takes_input), (path, method)
        if "422" in responses:
            assert responses["422"]["content"]["application/json"]["schema"] == ref


def test_the_committed_openapi_json_matches_what_the_app_generates(service):
    committed = json.loads(Path("frontend/openapi.json").read_text())
    assert committed == create_app(service).openapi(), "run scripts/export_schema.py"


# --- routes added after the envelope was built (policy settings, memory screens) -----------------


def csrf_headers(login):
    return ORIGIN | {"X-CSRF-Token": login.json()["csrf_token"]}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/settings/policy"),
        ("put", "/api/settings/policy"),
        ("get", "/api/memories"),
        ("post", "/api/memories"),
        ("get", "/api/purchases/00000000-0000-0000-0000-000000000000/receipt"),
    ],
)
def test_newer_routes_refuse_an_anonymous_caller_in_the_envelope(client, method, path):
    response = getattr(client, method)(path, headers=ORIGIN)
    assert response.status_code in (401, 403), response.text
    envelope(response, response.status_code)


def test_the_policy_settings_route_reports_a_bad_body_in_the_envelope(client):
    login = signed_in(client)
    response = client.put("/api/settings/policy", headers=csrf_headers(login), json={"bogus": 1})
    error = envelope(response, 422, "VALIDATION_ERROR")
    assert error["details"]


def test_the_memory_routes_report_validation_and_unknown_ids_in_the_envelope(client):
    login = signed_in(client)
    headers = csrf_headers(login)
    envelope(client.post("/api/memories", headers=headers, json={}), 422, "VALIDATION_ERROR")
    response = client.post(
        "/api/memories/00000000-0000-0000-0000-000000000000/delete", headers=headers, json={}
    )
    assert response.status_code >= 400
    envelope(response, response.status_code)
