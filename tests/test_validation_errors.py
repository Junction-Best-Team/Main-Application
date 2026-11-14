"""A 422 validation error must not echo what the client submitted (a password, a message).

FastAPI's default handler returns every error with its `input` (and sometimes `ctx`), which for a
missing field is the whole request body. The handler answers in the common error envelope
({"error": {"code": "VALIDATION_ERROR", "message", "details": [type, loc, msg]}}, TCT-008) and
never sends those values. The envelope itself is covered in test_error_envelope.py. Local app only.
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
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["message"]
    detail = error["details"]
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


def test_application_errors_keep_their_envelope(service):
    with TestClient(create_app(service)) as client:
        wrong = post(client, "/api/login", {"username": "buyer", "password": "wrong-password"})
        assert wrong.status_code == 401
        assert set(wrong.json()) == {"error"} and set(wrong.json()["error"]) == {"code", "message"}


def test_logout_clears_the_cookie_with_the_same_attributes_as_login(service):
    with TestClient(create_app(service)) as client:
        login = post(
            client,
            "/api/login",
            {"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
        )
        issued = login.headers["set-cookie"].lower()
        assert "httponly" in issued and "samesite=strict" in issued
        headers = ORIGIN | {"X-CSRF-Token": login.json()["csrf_token"]}
        out = client.post("/api/logout", headers=headers)
        assert out.status_code == 204
        cleared = out.headers["set-cookie"].lower()
        assert "aimo_session=" in cleared and "max-age=0" in cleared
        assert "httponly" in cleared and "samesite=strict" in cleared and "path=/" in cleared
