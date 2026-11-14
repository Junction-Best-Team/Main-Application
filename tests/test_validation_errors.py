"""A 422 validation error must not echo what the client submitted (a password, a message).

FastAPI's default handler returns every error with its `input` (and sometimes `ctx`), which for a
missing field is the whole request body. The handler keeps the response shape ({"detail": [...]}
with type, loc, msg) and removes those values everywhere. Local app only.
"""

import os

from fastapi.testclient import TestClient

from aimo.api import create_app

SECRET = "hunter2-do-not-echo"
ORIGIN = {"Origin": "http://testserver"}


def post(client, path, body, headers=None):
    return client.post(path, headers=headers or ORIGIN, json=body)


def shape(response):
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    for error in detail:
        assert {"type", "loc", "msg"} <= set(error)
        assert "input" not in error and "ctx" not in error
    return detail


def test_a_wrong_type_password_is_not_echoed(service):
    with TestClient(create_app(service)) as client:
        response = post(client, "/api/login", {"username": "buyer", "password": [SECRET]})
        assert SECRET not in response.text
        detail = shape(response)
        assert detail[0]["loc"] == ["body", "password"] and detail[0]["type"] == "string_type"


def test_a_missing_field_does_not_echo_the_other_submitted_values(service):
    with TestClient(create_app(service)) as client:
        response = post(client, "/api/login", {"username": SECRET})
        assert SECRET not in response.text
        detail = shape(response)
        assert detail == [
            {"type": "missing", "loc": ["body", "password"], "msg": "Field required"}
        ] or [(e["type"], e["loc"], e["msg"]) for e in detail] == [
            ("missing", ["body", "password"], "Field required")
        ]


def test_every_validation_error_is_stripped_not_just_login(service):
    with TestClient(create_app(service)) as client:
        login = post(
            client,
            "/api/login",
            {"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
        )
        headers = ORIGIN | {"X-CSRF-Token": login.json()["csrf_token"]}
        bad_uuid = client.get("/api/purchases/" + SECRET)  # path parameter that is not a UUID
        assert SECRET not in bad_uuid.text
        shape(bad_uuid)
        short_key = post(
            client,
            "/api/purchases/00000000-0000-0000-0000-000000000000/confirm",
            {
                "proposal_id": "00000000-0000-0000-0000-000000000000",
                "revision": 0,
                "idempotency_key": SECRET[:3],
            },
            headers,
        )
        assert SECRET[:3] + '"' not in short_key.text
        shape(short_key)


def test_application_errors_and_the_openapi_422_schema_are_unchanged(service):
    import json
    from pathlib import Path

    app = create_app(service)
    with TestClient(app) as client:
        wrong = post(client, "/api/login", {"username": "buyer", "password": "wrong-password"})
        assert wrong.status_code == 401
        assert set(wrong.json()) == {"error"} and set(wrong.json()["error"]) == {"code", "message"}
    stored = json.loads(Path("frontend/openapi.json").read_text())["components"]["schemas"]
    live = app.openapi()["components"]["schemas"]
    for name in ("HTTPValidationError", "ValidationError"):
        assert live[name] == stored[name]
