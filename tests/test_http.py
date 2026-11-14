import os
import re
from decimal import Decimal
from uuid import uuid4

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


@pytest.mark.parametrize("enabled", [False, True])
def test_session_exposes_current_recipe_feature_flag(http, monkeypatch, enabled):
    from aimo.config import settings

    monkeypatch.setattr(settings(), "recipe_planning_enabled", enabled)
    response = http.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert response.status_code == 200
    assert response.json()["recipe_planning_enabled"] is enabled
    assert http.get("/api/session").json()["recipe_planning_enabled"] is enabled
    monkeypatch.setattr(settings(), "recipe_planning_enabled", not enabled)
    assert http.get("/api/session").json()["recipe_planning_enabled"] is not enabled


def test_auth_inbox_csrf_and_logout(http, service, agent, mission):
    p = service.prepare_order(agent, mission)
    assert http.get("/api/approvals").status_code == 401
    assert (
        http.get(
            "/api/approvals", headers={"Authorization": "Bearer " + "removed-external-token"}
        ).status_code
        == 401
    )
    assert http.get("/api/agent/purchase-policy").status_code == 404
    assert http.get("/api/purchases/" + p["proposal_id"]).status_code == 401
    assert http.get("/mcp/").status_code == 404
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
    assert http.get("/api/purchases/" + p["proposal_id"]).status_code == 404
    assert (
        http.post(
            "/api/approvals/" + p["approval_id"] + "/decision",
            headers={"Origin": "http://testserver", "X-CSRF-Token": r.json()["csrf_token"]},
            json={"revision": 1, "decision": "approve"},
        ).status_code
        == 404
    )


def test_input_validation_and_api_errors(http, request_data):
    headers = login(http)
    assert (
        http.post("/api/conversations", json={"title": "meal"}, headers=headers).status_code == 422
    )
    assert (
        http.post(
            "/api/conversations",
            json={"title": "meal", "idempotency_key": str(uuid4()), "buyer_id": "other"},
            headers=headers,
        ).status_code
        == 422
    )
    for path in ("/api/nonexistent", "/api/agent/prepare_order", "/mcp", "/mcp/"):
        for method in ("get", "post"):
            response = http.request(method, path)
            assert response.status_code == 404
            assert response.headers["content-type"].startswith("application/json")
    assert http.get("/api/approvals?limit=100000").status_code == 422
    assert http.get("/health/live").status_code == 200


def test_login_rate_limit_and_wrong_origin(http):
    body = {"username": "buyer", "password": "wrong-password"}
    assert http.post("/api/login", json=body).status_code == 403
    responses = [
        http.post("/api/login", headers={"Origin": "http://testserver"}, json=body).status_code
        for _ in range(11)
    ]
    assert responses[:10] == [401] * 10 and responses[-1] == 429
    assert (
        int(
            http.post("/api/login", headers={"Origin": "http://testserver"}, json=body).headers[
                "Retry-After"
            ]
        )
        > 0
    )


def test_documentation_nonce_and_scoped_csp(http):
    docs = http.get("/docs")
    assert docs.status_code == 200
    policy = docs.headers["Content-Security-Policy"]
    nonce = re.search(r"'nonce-([^']+)'", policy)[1]
    scripts = re.findall(r"<script[^>]*>", docs.text)
    assert len(scripts) == 2 and all(f'nonce="{nonce}"' in script for script in scripts)
    assert "unsafe-inline" not in policy.split("script-src ")[1].split(";")[0]
    assert "cdn.jsdelivr.net" in policy.split("style-src ")[1].split(";")[0]
    assert docs.headers["Cache-Control"] == "no-store"
    assert nonce not in http.get("/docs").headers["Content-Security-Policy"]
    for path in ("/approvals", "/api/session", "/openapi.json"):
        strict = http.get(path).headers["Content-Security-Policy"]
        assert "script-src 'self'; style-src 'self';" in strict
        assert "unsafe-inline" not in strict and "cdn.jsdelivr.net" not in strict


def test_shared_purchasing_operations_and_both_commit_outcomes(
    service, agent, connector, request_data, confirm_terms
):
    from aimo.schemas import CommitRequest, LookupRequest, PrepareRequest, SearchRequest

    assert service.get_purchase_policy(agent)["rules"]["autonomous_limit"] == "1500.00"
    assert service.get_product(agent, "464306")["measures"]["L"]["value"] == "1"
    assert (
        service.search_products(agent, SearchRequest(query="464306"))["products"][0]["id"]
        == "464306"
    )
    assert service.search_products(agent, SearchRequest(query="000000"))["products"] == []
    lookup = service.check_price_and_availability(
        agent, LookupRequest(product_ids=["464306"], delivery_date=request_data["delivery_date"])
    )
    assert Decimal(lookup["products"]["464306"]["gross"]) == Decimal("1.70")
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert service.get_proposal(agent, p["proposal_id"])["revision"] == 1
    payload = {"proposal_id": p["proposal_id"], "revision": 1, "idempotency_key": str(uuid4())}
    connector.price_multiplier = Decimal("1.10")
    revised = service.commit_order(agent, CommitRequest.model_validate(payload))
    assert revised["status"] == "revised" and revised["revision"] == 2
    assert revised["snapshot"]["gross_total"] == "18.70"
    confirm_terms(revised)
    receipt = service.commit_order(agent, CommitRequest.model_validate(payload | {"revision": 2}))
    assert receipt["status"] == "accepted_mock"
    assert (
        service.commit_order(agent, CommitRequest.model_validate(payload | {"revision": 2}))
        == receipt
    )
    assert service.get_order(agent, receipt["order_id"]) == receipt


def test_historical_approval_links_current_autonomous_revision(
    http, service, connector, agent, mission
):
    # Repricing can remove the need for approval; the current-terms link must still work.
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id='demo-hotel' FOR UPDATE")
        rules = c.execute(
            "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
        ).fetchone()["rules"]
        rules["approved_product_ids"] = ["464306", "464398"]
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)", (js(rules),)
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    for line in mission.lines:
        line.substitutes_for = None
    p = service.prepare_order(agent, mission)
    csrf = login(http)
    old_url = "/api/approvals/" + p["approval_id"]
    assert (
        http.post(
            old_url + "/decision", headers=csrf, json={"revision": 1, "decision": "approve"}
        ).status_code
        == 200
    )
    payload = {"proposal_id": p["proposal_id"], "revision": 1, "idempotency_key": str(uuid4())}
    connector.price_multiplier = Decimal(".5")
    fresh = http.post(
        "/api/purchases/" + p["proposal_id"] + "/confirm", headers=csrf, json=payload
    ).json()
    assert fresh["approval_id"] is None and fresh["policy_outcome"] == "ready_to_commit"
    receipt = http.post(
        "/api/purchases/" + p["proposal_id"] + "/confirm",
        headers=csrf,
        json=payload | {"revision": 2, "idempotency_key": str(uuid4())},
    ).json()
    old = http.get(old_url).json()
    assert old["approval_status"] == "superseded" and old["order_id"] is None
    current = http.get("/api/purchases/" + p["proposal_id"]).json()
    assert current["revision"] == 2 and current["snapshot"]["gross_total"] == "850.00"
    assert current["order_id"] == receipt["order_id"] and current["order_status"] == "accepted_mock"
