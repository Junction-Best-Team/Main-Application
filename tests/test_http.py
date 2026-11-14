import os

import pytest
from fastapi.testclient import TestClient

from aimo.api import create_app
from aimo.auth import digest, hasher
from aimo.db import connection, js


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


def login(http):
    r = http.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert r.status_code == 200, r.text
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    return {"Origin": "http://testserver", "X-CSRF-Token": r.json()["csrf_token"]}


def test_auth_inbox_csrf_and_logout(http, service, agent, mission):
    p = service.prepare_order(agent, mission)
    assert http.get("/api/approvals").status_code == 401
    assert (
        http.get(
            "/api/approvals", headers={"Authorization": "Bearer " + os.environ["DEMO_AGENT_TOKEN"]}
        ).status_code
        == 401
    )
    assert http.get("/api/agent/purchase-policy").status_code == 401
    assert http.get("/mcp/").status_code == 401
    headers = login(http)
    assert http.get("/api/approvals").json()["items"][0]["proposal_id"] == p["proposal_id"]
    url = f"/api/approvals/{p['approval_id']}/decision"
    body = {"revision": 1, "decision": "approve"}
    assert http.post(url, json=body).status_code == 403
    assert (
        http.post(url, json=body, headers=headers | {"Origin": "https://evil.invalid"}).status_code
        == 403
    )
    response = http.post(url, json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["order_status"] == "not_placed"
    assert http.post("/api/logout", headers=headers).status_code == 204
    assert http.get("/api/session").status_code == 401


def test_cross_account_and_agent_isolation(http, service, agent, mission):
    p = service.prepare_order(agent, mission)
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other','999',1)")
        rules = c.execute("SELECT rules FROM policies WHERE buyer_id='demo-hotel'").fetchone()[
            "rules"
        ]
        c.execute("INSERT INTO policies(buyer_id,version,rules) VALUES('other',1,%s)", (js(rules),))
        c.execute(
            "INSERT INTO identities VALUES('other-agent','other','agent',true,%s,%s)",
            (digest("other-test-token"), js({"currency": "EUR", "autonomous_limit": "1500"})),
        )
        c.execute(
            "INSERT INTO identities VALUES('other-buyer','other','approver',true,%s,%s)",
            (
                hasher.hash("other-test-password"),
                js(
                    {
                        "currency": "EUR",
                        "max_gross": "5000",
                        "exceptions": ["spend", "substitution"],
                    }
                ),
            ),
        )
    h = {"Authorization": "Bearer other-test-token"}
    assert http.get("/api/agent/proposals/" + p["proposal_id"], headers=h).status_code == 404
    r = http.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "other-buyer", "password": "other-test-password"},
    )
    assert r.status_code == 200
    assert http.get("/api/approvals").json()["items"] == []
    assert http.get("/api/approvals/" + p["approval_id"]).status_code == 404
    assert (
        http.post(
            "/api/approvals/" + p["approval_id"] + "/decision",
            headers={"Origin": "http://testserver", "X-CSRF-Token": r.json()["csrf_token"]},
            json={"revision": 1, "decision": "approve"},
        ).status_code
        == 404
    )


def test_input_validation_and_api_errors(http, request_data):
    headers = {"Authorization": "Bearer " + os.environ["DEMO_AGENT_TOKEN"]}
    request_data["approved"] = True
    assert (
        http.post("/api/agent/prepare_order", json=request_data, headers=headers).status_code == 422
    )
    assert (
        http.post(
            "/api/agent/search_products",
            json={"query": "milk", "requirements": {"vegan": True}},
            headers=headers,
        ).status_code
        == 422
    )
    assert http.get("/api/nonexistent").status_code == 404
    assert http.get("/api/nonexistent").headers["content-type"].startswith("application/json")
    assert http.get("/api/approvals?limit=100000").status_code in (401, 422)
    assert http.get("/health/live").status_code == 200


def test_login_rate_limit_and_wrong_origin(http):
    body = {"username": "buyer", "password": "wrong-password"}
    assert http.post("/api/login", json=body).status_code == 403
    responses = [
        http.post("/api/login", headers={"Origin": "http://testserver"}, json=body).status_code
        for _ in range(11)
    ]
    assert responses[:10] == [401] * 10 and responses[-1] == 429
