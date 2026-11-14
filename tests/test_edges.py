"""Edge behaviour of the policy function, sessions, MCP errors, health, static frontend and search."""

import asyncio
import os
import sys
import types
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import aimo.api as api
import aimo.auth as auth
import aimo.search as search
from aimo.approval_policy import can_approve, evaluate_purchase
from aimo.config import Settings
from aimo.db import Problem, connection
from aimo.mcp_adapter import build_mcp
from aimo.schemas import Requirements, SearchRequest
from aimo.service import Service

# --- approval_policy -----------------------------------------------------------------------------

RULES = {
    "currency": "EUR",
    "autonomous_limit": "1500",
    "destinations": ["hotel"],
    "substitution": "requires_approval",
    "overbuy": "requires_approval",
}
AUTHORITY = {"currency": "EUR", "autonomous_limit": "1500"}
APPROVER = {"currency": "EUR", "max_gross": "5000", "exceptions": ["spend", "overbuy"]}


def snapshot(total="10.00", currency="EUR", excess="0"):
    return {
        "reasons": [],
        "currency": currency,
        "gross_total": total,
        "lines": [{"quantity": {"excess": excess}}],
    }


def evaluate(request=None, snap=None, rules=RULES, authority=AUTHORITY, approvers=(APPROVER,)):
    request = request or {"destination": "hotel", "lines": [{"substitutes_for": None}]}
    return evaluate_purchase(request, snap or snapshot(), rules, authority, list(approvers))


def reason_codes(result):
    return {r["code"] for r in result["reasons"]}


def test_missing_policy_or_authority_needs_resolution():
    for rules, authority in [({}, AUTHORITY), (RULES, {})]:
        result = evaluate(rules=rules, authority=authority)
        assert "MISSING_AUTHORITY" in reason_codes(result)
        assert result["policy_outcome"] in ("needs_resolution", "denied")
        assert result["policy_outcome"] != "ready_to_commit"


@pytest.mark.parametrize(
    "snap,authority",
    [
        (snapshot(currency="SEK"), AUTHORITY),
        (snapshot(), {"currency": "SEK", "autonomous_limit": "1500"}),
    ],
)
def test_currency_outside_authority_is_denied(snap, authority):
    result = evaluate(snap=snap, authority=authority)
    assert "CURRENCY_NOT_ALLOWED" in reason_codes(result)
    assert result["policy_outcome"] == "denied"


def test_unknown_currency_is_unresolved_not_denied():
    result = evaluate(snap=snapshot(currency=None))
    assert "CURRENCY_UNRESOLVED" in reason_codes(result)
    assert result["policy_outcome"] == "needs_resolution"


def test_an_unrecognised_exception_rule_neither_forbids_nor_asks():
    rules = RULES | {"overbuy": "allowed"}
    result = evaluate(snap=snapshot(excess="3"), rules=rules)
    assert not {"OVERBUY_FORBIDDEN", "OVERBUY_REQUIRES_APPROVAL"} & reason_codes(result)
    assert result["required_exceptions"] == []
    assert result["policy_outcome"] == "ready_to_commit"


def test_missing_exception_rule_defaults_to_forbidden():
    rules = {k: v for k, v in RULES.items() if k != "overbuy"}
    result = evaluate(snap=snapshot(excess="3"), rules=rules)
    assert "OVERBUY_FORBIDDEN" in reason_codes(result)
    assert result["policy_outcome"] == "denied"


def test_request_can_forbid_what_policy_would_allow_with_approval():
    request = {
        "destination": "hotel",
        "allow_overbuy": False,
        "lines": [{"substitutes_for": None}],
    }
    result = evaluate(request=request, snap=snapshot(excess="3"))
    assert "OVERBUY_FORBIDDEN" in reason_codes(result)


def test_approver_must_cover_amount_currency_and_every_exception():
    total = Decimal("2000")
    assert can_approve(APPROVER, total, "EUR", ["spend", "overbuy"])
    assert not can_approve(APPROVER, total, "EUR", ["substitution"])
    assert not can_approve(APPROVER, Decimal("5000.01"), "EUR", ["spend"])
    assert not can_approve(APPROVER, total, "SEK", ["spend"])
    assert not can_approve({}, total, "EUR", ["spend"])


def test_exception_without_eligible_approver_needs_resolution():
    result = evaluate(snap=snapshot(total="2000.00"), approvers=[{**APPROVER, "max_gross": "100"}])
    assert {"AUTONOMOUS_LIMIT_EXCEEDED", "NO_ELIGIBLE_APPROVER"} <= reason_codes(result)
    assert result["policy_outcome"] == "needs_resolution"
    assert evaluate(snap=snapshot(total="2000.00"))["policy_outcome"] == "approval_required"


# --- sessions and configuration ------------------------------------------------------------------


def test_session_secret_must_be_long_enough(monkeypatch):
    monkeypatch.setattr(
        auth, "settings", lambda: Settings(_env_file=None, approval_session_secret="short")
    )
    with pytest.raises(Problem) as error:
        auth.signer()
    assert (error.value.code, error.value.status) == ("SESSION_NOT_CONFIGURED", 503)


def test_valid_cookie_for_a_deactivated_approver_is_refused():
    with TestClient(api.create_app(Service())) as http:
        r = http.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
        )
        assert r.status_code == 200
        assert http.get("/api/session").status_code == 200
        with connection() as c:
            c.execute("UPDATE identities SET active=false WHERE id='buyer'")
        refused = http.get("/api/session")
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "UNAUTHENTICATED"


def test_expired_session_row_is_refused():
    with TestClient(api.create_app(Service())) as http:
        http.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
        )
        with connection() as c:
            c.execute("UPDATE sessions SET expires_at=now() - interval '1 minute'")
        assert http.get("/api/session").status_code == 401


# --- MCP -----------------------------------------------------------------------------------------


def test_mcp_tool_error_is_reported_as_error_result():
    token = os.environ["DEMO_AGENT_TOKEN"]
    with TestClient(api.create_app(Service())) as http:
        response = http.post(
            "/mcp/",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_product", "arguments": {"product_id": "no-such-id"}},
            },
        )
    result = response.json()["result"]
    assert result["isError"] is True
    assert "NOT_FOUND" in result["content"][0]["text"]


def test_mcp_tool_without_an_http_request_is_refused():
    """In-memory transport has no HTTP request, hence no bearer token: no anonymous tool calls."""
    from mcp.shared.memory import create_connected_server_and_client_session

    mcp = build_mcp(Service())

    async def call():
        async with create_connected_server_and_client_session(mcp._mcp_server) as session:
            return await session.call_tool("get_purchase_policy", {})

    result = asyncio.run(call())
    assert result.isError is True
    assert "Authenticated HTTP transport is required" in result.content[0].text


# --- health and static frontend ------------------------------------------------------------------


def test_ready_reports_model_and_upstream_mode():
    with TestClient(api.create_app(Service())) as http:
        body = http.get("/health/ready").json()
    assert body["status"] == "ready"
    assert body["upstream_mode"] == "fixture" and body["model"] == "fixture-hash-v1:384"


def test_ready_fails_when_the_serving_model_differs_from_the_catalog(monkeypatch):
    monkeypatch.setattr(search, "model_key", lambda: "some-other-model@rev")
    with TestClient(api.create_app(Service())) as http:
        r = http.get("/health/ready")
    assert r.status_code == 503 and r.json()["error"]["code"] == "INDEX_NOT_READY"


def test_ready_loads_the_real_embedding_model_for_that_backend(monkeypatch):
    loaded = []
    cfg = Settings(_env_file=None, embedding_backend="sentence_transformers")
    monkeypatch.setattr(api, "settings", lambda: cfg)
    monkeypatch.setattr(search, "model_key", lambda: "fixture-hash-v1:384")  # matches the catalog
    monkeypatch.setattr(search, "model", lambda: loaded.append(True))
    with TestClient(api.create_app(Service())) as http:
        assert http.get("/health/ready").status_code == 200
    assert loaded == [True]


def static_app(monkeypatch, dist):
    cfg = Settings(_env_file=None, frontend_dist=str(dist))
    monkeypatch.setattr(api, "settings", lambda: cfg)
    return TestClient(api.create_app(Service()))


def test_built_frontend_is_served_for_spa_routes_and_assets(monkeypatch, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('x')")
    (tmp_path / "index.html").write_text("<!doctype html><title>inbox</title>")
    with static_app(monkeypatch, tmp_path) as http:
        for path in ("/", "/login", "/approvals", "/approvals/abc", "/purchases/abc"):
            r = http.get(path)
            assert r.status_code == 200 and "<title>inbox</title>" in r.text, path
            assert r.headers["cache-control"] == "no-cache"
        asset = http.get("/assets/app.js")
        assert asset.status_code == 200 and "console.log" in asset.text


def test_missing_frontend_build_is_a_clear_503(monkeypatch, tmp_path):
    with static_app(monkeypatch, tmp_path / "absent") as http:
        r = http.get("/approvals")
    assert r.status_code == 503 and "Build the frontend" in r.json()["error"]


# --- search --------------------------------------------------------------------------------------


def test_search_refuses_when_no_catalog_is_published():
    with connection() as c:
        saved = c.execute("SELECT generation FROM active_catalog").fetchone()["generation"]
        c.execute("DELETE FROM active_catalog")
    try:
        with connection() as c:
            identity = c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()
        with pytest.raises(Problem) as error:
            search.search_products(identity, SearchRequest(query="milk"))
        assert (error.value.code, error.value.status) == ("INDEX_NOT_READY", 503)
    finally:
        with connection() as c:
            c.execute("INSERT INTO active_catalog(singleton,generation) VALUES(true,%s)", (saved,))


def test_search_refuses_a_catalog_built_with_another_model(agent, monkeypatch):
    monkeypatch.setattr(search, "model_key", lambda: "intfloat/other@abc")
    with pytest.raises(Problem) as error:
        search.search_products(agent, SearchRequest(query="milk"))
    assert (error.value.code, error.value.status) == ("MODEL_MISMATCH", 503)


def test_search_drops_candidates_that_fail_requirement_checks_even_if_the_filter_let_them_in(
    agent, monkeypatch
):
    baseline = search.search_products(agent, SearchRequest(query="milk", limit=20))
    ids = [p["id"] for p in baseline["products"]]
    assert "464398" in ids and len(ids) > 1
    real = search.requirement_reasons

    def flag(p, requirements):
        if p["id"] == "464398":
            return [{"code": "TEST_FLAG"}]
        return real(p, requirements)

    monkeypatch.setattr(search, "requirement_reasons", flag)
    filtered = search.search_products(agent, SearchRequest(query="milk", limit=20))
    assert [p["id"] for p in filtered["products"]] == [i for i in ids if i != "464398"]


def test_search_limit_is_respected_and_scores_descend(agent):
    result = search.search_products(
        agent, SearchRequest(query="milk", requirements=Requirements(), limit=2)
    )
    scores = [p["score"] for p in result["products"]]
    assert len(scores) == 2 and scores == sorted(scores, reverse=True)
    assert all(p["match_is_suitability_proof"] is False for p in result["products"])


# --- embedding model wiring (no download, no torch) ----------------------------------------------


def test_real_model_key_embeds_with_query_and_passage_prefixes_and_pins_the_revision(monkeypatch):
    cfg = Settings(_env_file=None, embedding_backend="sentence_transformers")
    monkeypatch.setattr(search, "settings", lambda: cfg)
    assert search.model_key() == (f"intfloat/multilingual-e5-small@{search.PINNED_REVISION}")
    pinned = Settings(
        _env_file=None,
        embedding_backend="sentence_transformers",
        embedding_model_revision="abc123",
    )
    monkeypatch.setattr(search, "settings", lambda: pinned)
    assert search.model_key().endswith("@abc123")

    built, encoded = [], []

    class FakeArray(list):
        def tolist(self):
            return list(self)

    class FakeModel:
        def __init__(self, name, **kwargs):
            built.append((name, kwargs))

        def encode(self, texts, **kwargs):
            encoded.append((texts, kwargs))
            return FakeArray([[0.5] * 384 for _ in texts])

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(set_num_threads=lambda n: None))
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeModel)
    )
    search.model.cache_clear()
    monkeypatch.setattr(search, "settings", lambda: cfg)
    try:
        assert search.embed(["milk"], query=True) == [[0.5] * 384]
        search.embed(["milk", "cream"])
    finally:
        search.model.cache_clear()
    assert [t for t, _ in encoded] == [["query: milk"], ["passage: milk", "passage: cream"]]
    assert all(kw["normalize_embeddings"] is True for _, kw in encoded)
    assert len(built) == 1  # the model is built once and cached
    name, kwargs = built[0]
    assert name == "intfloat/multilingual-e5-small"
    assert kwargs["revision"] == search.PINNED_REVISION
    assert kwargs["trust_remote_code"] is False and kwargs["device"] == "cpu"


# --- agent bearer credentials and CSRF -----------------------------------------------------------


@pytest.mark.parametrize(
    "header", [None, "", "Basic abc", "bearer lowercase", "Bearer wrong-token"]
)
def test_agent_credentials_must_be_an_exact_bearer_token(header):
    with pytest.raises(Problem) as error:
        auth.agent_identity(header)
    assert (error.value.code, error.value.status) == ("UNAUTHENTICATED", 401)


def test_agent_credential_of_an_inactive_agent_is_refused():
    token = os.environ["DEMO_AGENT_TOKEN"]
    assert auth.agent_identity("Bearer " + token)["id"] == "demo-agent"
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='demo-agent'")
    with pytest.raises(Problem):
        auth.agent_identity("Bearer " + token)


def test_csrf_check_needs_the_matching_token_and_origin():
    identity = {"csrf_hash": auth.digest("right-token")}
    auth.csrf_check(identity, "right-token", "http://testserver")
    for token, origin, code in [
        (None, "http://testserver", "CSRF_REJECTED"),
        ("wrong", "http://testserver", "CSRF_REJECTED"),
        ("right-token", "http://evil.test", "ORIGIN_REJECTED"),
        ("right-token", None, "ORIGIN_REJECTED"),
    ]:
        with pytest.raises(Problem) as error:
            auth.csrf_check(identity, token, origin)
        assert (error.value.code, error.value.status) == (code, 403)


def test_duplicate_product_lines_are_rejected_with_a_validation_error(request_data):
    from pydantic import ValidationError

    from aimo.schemas import PurchaseRequest

    request_data["lines"] = [
        {"product_id": "464306", "amount": "1", "unit": "L"},
        {"product_id": "464306", "amount": "2", "unit": "L"},
    ]
    with pytest.raises(ValidationError, match="duplicate product IDs"):
        PurchaseRequest.model_validate(request_data)
