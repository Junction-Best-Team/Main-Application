"""Browser memory management API: session, Origin/CSRF, revisions and ownership."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_memory import add_user, other_buyer

from aimo.api import create_app
from aimo.db import connection

ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


def login(client, username="buyer"):
    r = client.post(
        "/api/login",
        headers=ORIGIN,
        json={"username": username, "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert r.status_code == 200, r.text
    return ORIGIN | {"X-CSRF-Token": r.json()["csrf_token"]}


def create(client, headers, **body):
    payload = {"scope": "buyer", "key": "default.portions", "value": {"portions": 200}}
    return client.post(
        "/api/memories", headers=headers, json=payload | {"idempotency_key": str(uuid4())} | body
    )


def test_memory_api_requires_session_origin_and_csrf(http):
    body = {
        "scope": "self",
        "key": "preference.reply_style",
        "value": {"length": "short"},
        "idempotency_key": str(uuid4()),
    }
    assert http.get("/api/memories").status_code == 401
    assert http.post("/api/memories", headers=ORIGIN, json=body).status_code == 401
    headers = login(http)
    assert http.post("/api/memories", json=body).status_code == 403
    assert http.post("/api/memories", headers=ORIGIN, json=body).json()["error"]["code"] == (
        "CSRF_REJECTED"
    )
    wrong = headers | {"Origin": "http://evil.test"}
    assert http.post("/api/memories", headers=wrong, json=body).json()["error"]["code"] == (
        "ORIGIN_REJECTED"
    )
    created = http.post("/api/memories", headers=headers, json=body)
    assert created.status_code == 200, created.text
    mid = created.json()["memory_id"]
    update = {"expected_revision": 1, "value": {"length": "detailed"}, "idempotency_key": "k" * 8}
    assert http.put(f"/api/memories/{mid}", headers=ORIGIN, json=update).status_code == 403
    delete = {"expected_revision": 1, "idempotency_key": "d" * 8}
    assert http.post(f"/api/memories/{mid}/delete", headers=ORIGIN, json=delete).status_code == 403
    with connection() as c:
        assert c.execute("SELECT revision FROM memories").fetchone()["revision"] == 1
    # Revoked accounts lose access on the next request.
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    assert http.get("/api/memories").status_code == 401


def test_memory_api_create_list_update_delete_with_revisions(http):
    headers = login(http)
    key = str(uuid4())
    first = create(http, headers, idempotency_key=key)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["status"] == "created" and data["revision"] == 1 and not data["replayed"]
    item = data["memory"]
    assert item["scope"] == "buyer" and item["owner_id"] is None and item["kind"] == "default"
    assert item["created_by"] == "buyer" and item["source_message_id"] is None
    retry = create(http, headers, idempotency_key=key)
    assert retry.json()["replayed"] and retry.json()["memory_id"] == data["memory_id"]
    conflict = create(http, headers, idempotency_key=key, value={"portions": 150})
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )
    duplicate = create(http, headers, value={"portions": 150})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "MEMORY_EXISTS"
    personal = create(
        http,
        headers,
        scope="self",
        key="instruction.cheaper_first",
        value={"text": "Show cheaper alternatives before preparing a basket."},
        description="Workflow",
    )
    assert personal.json()["memory"]["owner_id"] == "buyer"
    listed = http.get("/api/memories").json()
    assert {i["key"] for i in listed["items"]} == {"default.portions", "instruction.cheaper_first"}
    assert [i["key"] for i in http.get("/api/memories?scope=self").json()["items"]] == [
        "instruction.cheaper_first"
    ]
    assert [i["key"] for i in http.get("/api/memories?q=cheaper").json()["items"]] == [
        "instruction.cheaper_first"
    ]
    assert http.get("/api/memories?kind=default&limit=1").json()["next_offset"] is None
    assert http.get("/api/memories?limit=51").status_code == 422
    mid = data["memory_id"]
    stale = {"expected_revision": 2, "value": {"portions": 150}, "idempotency_key": str(uuid4())}
    response = http.put(f"/api/memories/{mid}", headers=headers, json=stale)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MEMORY_REVISION_CONFLICT"
    updated = http.put(
        f"/api/memories/{mid}", headers=headers, json=stale | {"expected_revision": 1}
    )
    assert updated.status_code == 200 and updated.json()["memory"]["value"] == {"portions": 150}
    assert updated.json()["revision"] == 2
    gone = {"expected_revision": 2, "idempotency_key": str(uuid4())}
    deleted = http.post(f"/api/memories/{mid}/delete", headers=headers, json=gone)
    assert deleted.status_code == 200 and deleted.json()["status"] == "deleted"
    assert deleted.json()["memory"] is None
    again = http.post(f"/api/memories/{mid}/delete", headers=headers, json=gone)
    assert again.json()["replayed"] and again.json()["status"] == "deleted"
    missing = http.post(
        f"/api/memories/{mid}/delete",
        headers=headers,
        json=gone | {"idempotency_key": str(uuid4())},
    )
    assert missing.status_code == 404
    assert [i["key"] for i in http.get("/api/memories").json()["items"]] == [
        "instruction.cheaper_first"
    ]


def test_memory_api_validation_and_ownership(http, service):
    add_user("chef")
    other_buyer()
    headers = login(http)
    bad_key = create(http, headers, key="policy.approved_product_ids")
    assert bad_key.status_code == 422
    bad_value = create(http, headers, value={"portions": "many"})
    assert bad_value.status_code == 422 and bad_value.json()["error"]["code"] == (
        "MEMORY_VALUE_INVALID"
    )
    secret = create(http, headers, key="instruction.login", value={"text": "password is x"})
    assert secret.json()["error"]["code"] == "MEMORY_SENSITIVE_DATA"
    assert create(http, headers, owner_id="chef").status_code == 422  # Server resolves owners.
    mine = create(
        http, headers, scope="self", key="preference.reply_style", value={"length": "short"}
    )
    mid = mine.json()["memory_id"]
    with (
        TestClient(create_app(service)) as chef_client,
        TestClient(create_app(service)) as outsider,
    ):
        chef = login(chef_client, "chef")
        assert chef_client.get("/api/memories").json()["items"] == []
        body = {"expected_revision": 1, "idempotency_key": str(uuid4())}
        response = chef_client.post(f"/api/memories/{mid}/delete", headers=chef, json=body)
        assert response.status_code == 404
        shared = create(chef_client, chef).json()
        assert shared["memory"]["created_by"] == "chef"
        other = login(outsider, "other-buyer")
        assert outsider.get("/api/memories").json()["items"] == []
        update = {"expected_revision": 1, "value": {"portions": 1}, "idempotency_key": str(uuid4())}
        assert (
            outsider.put(
                f"/api/memories/{shared['memory_id']}", headers=other, json=update
            ).status_code
            == 404
        )
    keys = {i["key"]: i["created_by"] for i in http.get("/api/memories").json()["items"]}
    assert keys == {"preference.reply_style": "buyer", "default.portions": "chef"}
