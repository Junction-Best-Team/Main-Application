"""Edge behaviour of the policy function, sessions, health, static frontend and search."""

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
from aimo.schemas import Requirements, SearchRequest
from aimo.service import Service

# --- approval_policy -----------------------------------------------------------------------------

RULES = {
    "currency": "EUR",
    "destinations": ["hotel"],
    "substitution": "requires_approval",
    "overbuy": "requires_approval",
    "approved_product_ids": ["464306"],
}
APPROVER = {"currency": "EUR", "max_gross": "5000", "exceptions": ["overbuy"]}


def snapshot(total="10.00", currency="EUR", excess="0"):
    return {
        "reasons": [],
        "currency": currency,
        "gross_total": total,
        "lines": [{"quantity": {"excess": excess}}],
    }


def evaluate(request=None, snap=None, rules=RULES, approvers=(APPROVER,)):
    request = request or {
        "destination": "hotel",
        "lines": [{"product_id": "464306", "substitutes_for": None}],
    }
    return evaluate_purchase(request, snap or snapshot(), rules, list(approvers))


def reason_codes(result):
    return {r["code"] for r in result["reasons"]}


def test_missing_policy_or_approver_needs_resolution():
    # Q-35: an agent holds no authority, so only the policy and the human approvers can be missing.
    result = evaluate(rules={})
    assert "MISSING_AUTHORITY" in reason_codes(result)
    assert result["policy_outcome"] in ("needs_resolution", "denied")
    no_approver = evaluate(approvers=())
    assert "NO_ELIGIBLE_APPROVER" in reason_codes(no_approver)  # Q-37 / POL-014
    assert no_approver["policy_outcome"] == "needs_resolution"


def test_currency_outside_authority_is_denied():
    # The agent-currency case is gone with the agent's authority (Q-35); an approver in another
    # currency is covered by test_approver_must_cover_amount_currency_and_every_exception.
    result = evaluate(snap=snapshot(currency="SEK"))
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


def test_missing_product_scope_blocks_substitution_rules_instead_of_assuming_one():
    rules = {k: v for k, v in RULES.items() if k != "approved_product_ids"}
    result = evaluate(rules=rules)
    assert "PRODUCT_SCOPE_UNCONFIGURED" in reason_codes(result)
    assert result["policy_outcome"] == "needs_resolution"


def test_product_outside_the_approved_scope_counts_as_a_substitution_needing_approval():
    request = {"destination": "hotel", "lines": [{"product_id": "999999", "substitutes_for": None}]}
    capable = {**APPROVER, "exceptions": ["substitution"]}
    result = evaluate(request=request, approvers=[capable])
    assert "SUBSTITUTION_REQUIRES_APPROVAL" in reason_codes(result)
    assert result["required_exceptions"] == ["substitution"]
    assert result["policy_outcome"] == "approval_required"
    # With only an approver who cannot clear substitutions, it needs resolution, not approval.
    stuck = evaluate(request=request)
    assert "NO_ELIGIBLE_APPROVER" in reason_codes(stuck)
    assert stuck["policy_outcome"] == "needs_resolution"


def test_missing_exception_rule_defaults_to_forbidden():
    rules = {k: v for k, v in RULES.items() if k != "overbuy"}
    result = evaluate(snap=snapshot(excess="3"), rules=rules)
    assert "OVERBUY_FORBIDDEN" in reason_codes(result)
    assert result["policy_outcome"] == "denied"


def test_request_can_forbid_what_policy_would_allow_with_approval():
    request = {
        "destination": "hotel",
        "allow_overbuy": False,
        "lines": [{"product_id": "464306", "substitutes_for": None}],
    }
    result = evaluate(request=request, snap=snapshot(excess="3"))
    assert "OVERBUY_FORBIDDEN" in reason_codes(result)


def test_approver_must_cover_amount_currency_and_every_exception():
    total = Decimal("2000")
    assert can_approve(APPROVER, total, "EUR", ["overbuy"])
    assert can_approve(APPROVER, total, "EUR", [])
    assert not can_approve(APPROVER, total, "EUR", ["substitution"])
    assert not can_approve(APPROVER, Decimal("5000.01"), "EUR", ["overbuy"])
    assert not can_approve(APPROVER, total, "SEK", ["overbuy"])
    assert not can_approve({}, total, "EUR", ["overbuy"])


def test_total_above_every_approvers_maximum_needs_resolution():
    # Q-35/Q-37: no autonomous limit; the approver's maximum is the only spending limit.
    small = [{**APPROVER, "max_gross": "100"}]
    result = evaluate(snap=snapshot(total="2000.00"), approvers=small)
    assert reason_codes(result) == {"NO_ELIGIBLE_APPROVER"}
    assert result["policy_outcome"] == "needs_resolution" and result["required_exceptions"] == []
    with_exception = evaluate(snap=snapshot(total="2000.00", excess="3"), approvers=small)
    assert "NO_ELIGIBLE_APPROVER" in reason_codes(with_exception)
    assert with_exception["policy_outcome"] == "needs_resolution"
    assert evaluate(snap=snapshot(total="2000.00"))["policy_outcome"] == "ready_to_commit"


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


# --- health and static frontend ------------------------------------------------------------------


def test_ready_is_a_bare_status_and_names_neither_the_model_nor_the_supplier_mode():
    with TestClient(api.create_app(Service())) as http:
        response = http.get("/health/ready")
    assert response.status_code == 200 and response.json() == {"status": "ready"}
    assert "fixture" not in response.text and "model" not in response.text


def test_a_failing_ready_names_neither_the_model_nor_the_schema(monkeypatch):
    monkeypatch.setattr(search, "model_key", lambda: "some-other-model@rev")
    with TestClient(api.create_app(Service())) as http:
        response = http.get("/health/ready")
    assert response.status_code == 503
    assert "some-other-model" not in response.text and "fixture-hash" not in response.text


def test_ready_fails_when_the_serving_model_differs_from_the_catalog(monkeypatch):
    monkeypatch.setattr(search, "model_key", lambda: "some-other-model@rev")
    with TestClient(api.create_app(Service())) as http:
        r = http.get("/health/ready")
    assert r.status_code == 503 and r.json()["error"]["code"] == "INDEX_NOT_READY"


def test_ready_checks_the_catalog_model_but_does_not_load_the_embedding_model(monkeypatch):
    """Readiness compares model keys and vector sizes; loading weights is the worker's job."""
    cfg = Settings(_env_file=None, embedding_backend="sentence_transformers")
    monkeypatch.setattr(api, "settings", lambda: cfg)
    monkeypatch.setattr(search, "model_key", lambda: "fixture-hash-v1:384")  # matches the catalog

    def forbidden():
        raise AssertionError("the API process must not load the embedding model")

    monkeypatch.setattr(search, "model", forbidden)
    with TestClient(api.create_app(Service())) as http:
        assert http.get("/health/ready").status_code == 200


def test_ready_fails_when_the_vector_size_differs_from_the_catalog(monkeypatch):
    monkeypatch.setattr(search, "dimensions", lambda: 1536)
    with TestClient(api.create_app(Service())) as http:
        r = http.get("/health/ready")
    assert r.status_code == 503 and r.json()["error"]["code"] == "INDEX_NOT_READY"


def test_the_api_app_does_not_serve_the_frontend():
    """The frontend is a separate app since the runtime split; the API only answers /api and health."""
    with TestClient(api.create_app(Service())) as http:
        for path in ("/", "/login", "/approvals", "/purchases/abc", "/assets/app.js"):
            assert http.get(path).status_code == 404, path
        assert http.get("/health/live").status_code == 200


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
    assert search.model_key() == (f"intfloat/multilingual-e5-small@{search.EMBEDDING_REVISION}")
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
    assert kwargs["revision"] == search.EMBEDDING_REVISION
    assert kwargs["trust_remote_code"] is False and kwargs["device"] == "cpu"


# --- agent bearer credentials and CSRF -----------------------------------------------------------


def test_internal_agent_is_resolved_from_the_buyer_mapping_never_from_input():
    agent = auth.internal_agent({"buyer_id": "demo-hotel"})
    assert agent["role"] == "agent" and agent["buyer_id"] == "demo-hotel"
    assert agent["id"].startswith("internal:")


def test_buyer_without_a_provisioned_internal_agent_is_refused():
    with pytest.raises(Problem) as error:
        auth.internal_agent({"buyer_id": "no-such-buyer"})
    assert (error.value.code, error.value.status) == ("AGENT_NOT_CONFIGURED", 503)


def test_inactive_internal_agent_is_refused():
    agent = auth.internal_agent({"buyer_id": "demo-hotel"})
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id=%s", (agent["id"],))
    with pytest.raises(Problem) as error:
        auth.internal_agent({"buyer_id": "demo-hotel"})
    assert error.value.code == "AGENT_NOT_CONFIGURED"


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

    from aimo.schemas import PrepareRequest

    request_data["lines"] = [
        {"product_id": "464306", "amount": "1", "unit": "L"},
        {"product_id": "464306", "amount": "2", "unit": "L"},
    ]
    with pytest.raises(ValidationError, match="duplicate product IDs"):
        PrepareRequest.model_validate(request_data)
