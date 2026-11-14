import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from argon2.exceptions import VerificationError
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from aimo import approval_workflow as workflow
from aimo import auth
from aimo.catalog import quantity
from aimo.cli import set_product_scope
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, js, now, pool
from aimo.fixtures import fixture_facts
from aimo.ingest import ingest_file, publish
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest, SearchRequest
from aimo.service import Service


def policy(**changes):
    with connection() as c:
        buyer = c.execute("SELECT * FROM buyers WHERE id='demo-hotel' FOR UPDATE").fetchone()
        row = c.execute(
            "SELECT * FROM policies WHERE buyer_id='demo-hotel' AND version=%s",
            (buyer["current_policy"],),
        ).fetchone()
        version = buyer["current_policy"] + 1
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',%s,%s)",
            (version, js(row["rules"] | changes)),
        )
        c.execute("UPDATE buyers SET current_policy=%s WHERE id='demo-hotel'", (version,))


def commit(p):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )


@pytest.mark.parametrize(
    "rule,allow,outcome",
    [
        ("requires_approval", True, "approval_required"),
        ("forbidden", True, "denied"),
        ("allowed", False, "denied"),
    ],
)
def test_undeclared_replacement_cannot_bypass_buyer_scope(
    service, agent, buyer, request_data, rule, allow, outcome, confirm_terms
):
    policy(substitution=rule)
    request_data.update(
        lines=[{"product_id": "464398", "amount": "10", "unit": "L"}], allow_substitution=allow
    )
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == outcome
    assert p["request"]["lines"][0]["substitutes_for"] is None
    if outcome == "approval_required":
        confirm_terms(p)  # the confirmation alone is not an exception approval
    with pytest.raises(Problem) as error:
        service.commit_order(agent, commit(p))
    assert error.value.code == (
        "APPROVAL_REQUIRED" if outcome == "approval_required" else "COMMIT_BLOCKED"
    )
    if outcome == "approval_required":
        workflow.record_human_decision(
            buyer, p["approval_id"], DecisionRequest(revision=1, decision="approve")
        )
        assert service.commit_order(agent, commit(p))["status"] == "accepted_mock"


def test_missing_product_scope_fails_closed_and_provisioning_versions_policy(
    service, agent, request_data
):
    policy(approved_product_ids=None)
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "needs_resolution" and p["approval_id"] is None
    assert "PRODUCT_SCOPE_UNCONFIGURED" in {r["code"] for r in p["reasons"]}
    version = set_product_scope("demo-hotel", ["464306"])
    assert version == 3 and set_product_scope("demo-hotel", ["464306"]) == 3
    with connection() as c:
        assert (
            c.execute(
                "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=2"
            ).fetchone()["rules"]["approved_product_ids"]
            is None
        )
    revised = service.commit_order(agent, commit(p))
    assert revised["status"] == "revised" and revised["policy_outcome"] == "ready_to_commit"


@pytest.mark.parametrize(
    "amount,step,whole,expected,excess",
    [
        ("10", "1", True, "3", "0"),
        ("20", "1", True, "6", "0"),
        ("30", "1", True, "9", "0"),
        ("20", ".01", False, "6", "0"),
        ("20", "1.5", True, "6", "0"),
        ("20.0001", "1.5", True, "9", "9.9999"),
    ],
)
def test_pack_ceiling_uses_exact_rationals(amount, step, whole, expected, excess):
    p = fixture_facts()[0]
    p.update(units={"ST": "10", "REQUEST": "3"}, order_step=step)
    q = quantity(p, Decimal(amount), "REQUEST", whole)
    assert Decimal(q["sales_quantity"]) == Decimal(expected)
    assert Decimal(q["excess"]) == Decimal(excess)


def test_prepare_retries_are_atomic_and_survive_restart(
    service, agent, buyer, mission, confirm_terms
):
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: service.prepare_order(agent, mission), range(8)))
    assert len({p["proposal_id"] for p in results}) == len({p["approval_id"] for p in results}) == 1
    p = results[0]
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM approvals").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM prepare_requests").fetchone()["n"] == 1

    class Broken:
        def lookup(self, *args):
            raise AssertionError("completed preparation retry must not call supplier")

    restarted = Service(Broken())
    assert restarted.prepare_order(agent, mission)["proposal_id"] == p["proposal_id"]
    with pytest.raises(Problem) as error:
        restarted.prepare_order(agent, mission.model_copy(update={"destination": "other"}))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    confirm_terms(p)
    workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=1, decision="approve")
    )
    receipt = service.commit_order(agent, commit(p))
    assert restarted.prepare_order(agent, mission)["order_id"] == receipt["order_id"]


def test_prepare_key_is_scoped_to_authenticated_agent(service, agent, request_data):
    request = PrepareRequest(**request_data)
    first = service.prepare_order(agent, request)
    with connection() as c:
        second_agent = c.execute(
            "INSERT INTO identities VALUES('second-agent','demo-hotel','agent',true,'test-hash',%s) RETURNING *",
            (js(agent["authority"]),),
        ).fetchone()
    second = service.prepare_order(second_agent, request)
    assert first["proposal_id"] != second["proposal_id"]
    assert service.prepare_order(second_agent, request)["proposal_id"] == second["proposal_id"]


def test_failed_preparation_does_not_consume_retry_key(service, agent, mission, monkeypatch):
    original = workflow.audit

    def fail(*args, **kwargs):
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(workflow, "audit", fail)
    with pytest.raises(RuntimeError):
        service.prepare_order(agent, mission)
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM prepare_requests").fetchone()["n"] == 0
    monkeypatch.setattr(workflow, "audit", original)
    assert service.prepare_order(agent, mission)["policy_outcome"] == "approval_required"


@pytest.mark.parametrize("change", ["inactive", "role"])
def test_cached_identity_does_not_bypass_current_authority(service, agent, mission, change):
    with connection() as c:
        if change == "inactive":
            c.execute("UPDATE identities SET active=false WHERE id='demo-agent'")
        else:
            c.execute("UPDATE identities SET role='approver' WHERE id='demo-agent'")
    with pytest.raises(Problem) as error:
        service.prepare_order(agent, mission)
    assert error.value.code == "AUTHORITY_REVOKED"


def test_inbox_has_bounded_queries_and_preserves_details(
    service, agent, buyer, mission, monkeypatch
):
    proposals = [
        service.prepare_order(agent, mission.model_copy(update={"idempotency_key": str(uuid4())}))
        for _ in range(20)
    ]
    expected = {
        p["proposal_id"]: workflow.approval_detail(buyer, p["approval_id"]) for p in proposals
    }
    calls = []

    @contextmanager
    def counted_connection():
        with connection() as c:

            class Counted:
                def execute(self, query, *args):
                    calls.append(query)
                    return c.execute(query, *args)

            yield Counted()

    monkeypatch.setattr(workflow, "connection", counted_connection)
    page = workflow.list_approvals(buyer, limit=20)
    assert len(page["items"]) == 20 and len(calls) == 6
    for p in page["items"]:
        assert p == expected[p["proposal_id"]]


def test_successful_logins_do_not_consume_failure_budget():
    for _ in range(20):
        assert (
            auth.login("buyer", os.environ["DEMO_BUYER_PASSWORD"], "198.51.100.1")[0]["id"]
            == "buyer"
        )
    failure_key = auth.digest("failures:198.51.100.1:buyer")
    with connection() as c:
        assert not c.execute("SELECT 1 FROM login_attempts WHERE key=%s", (failure_key,)).fetchone()


def test_failed_client_does_not_lock_other_client():
    for _ in range(10):
        with pytest.raises(Problem, match="incorrect"):
            auth.login("buyer", "wrong-password", "198.51.100.1")
    with pytest.raises(Problem) as error:
        auth.login("buyer", os.environ["DEMO_BUYER_PASSWORD"], "198.51.100.1")
    assert error.value.code == "LOGIN_RATE_LIMIT"
    assert (
        auth.login("buyer", os.environ["DEMO_BUYER_PASSWORD"], "198.51.100.2")[0]["id"] == "buyer"
    )


def test_username_spray_is_bounded_and_expired_auth_rows_are_cleaned(monkeypatch):
    def invalid(*args):
        raise VerificationError("test failure")

    monkeypatch.setattr(auth, "hasher", SimpleNamespace(verify=invalid))
    for i in range(60):
        with pytest.raises(Problem) as error:
            auth.login(f"unknown-{i}", "wrong", "198.51.100.3")
        assert error.value.code == "LOGIN_FAILED"
    with pytest.raises(Problem) as error:
        auth.login("another-name", "wrong", "198.51.100.3")
    assert error.value.code == "LOGIN_RATE_LIMIT"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM login_attempts").fetchone()["n"] == 61
        c.execute(
            "INSERT INTO sessions VALUES('expired-session','buyer','test-csrf',%s)",
            (now() - timedelta(hours=1),),
        )
    future = now() + timedelta(minutes=6)
    monkeypatch.setattr(auth, "now", lambda: future)
    with pytest.raises(Problem, match="incorrect"):
        auth.login("new-name", "wrong", "198.51.100.3")
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM login_attempts").fetchone()["n"] == 2
        assert not c.execute("SELECT 1 FROM sessions WHERE token_hash='expired-session'").fetchone()


@pytest.mark.parametrize(
    "peer,expected", [("10.20.0.5", "198.51.100.7"), ("203.0.113.5", "203.0.113.5")]
)
def test_forwarded_client_addresses_only_from_trusted_ingress(peer, expected):
    async def echo(scope, receive, send):
        await JSONResponse({"client": scope["client"][0]})(scope, receive, send)

    app = ProxyHeadersMiddleware(echo, trusted_hosts="10.20.0.0/24")
    client = TestClient(app, client=(peer, 123))
    assert client.get("/", headers={"X-Forwarded-For": "198.51.100.7"}).json()["client"] == expected


def test_pool_reuses_connection_and_rolls_back_failed_work(monkeypatch):
    monkeypatch.setattr(settings(), "db_pool_max_size", 1)
    monkeypatch.setattr(settings(), "db_pool_timeout_seconds", 0.05)
    with pytest.raises(RuntimeError):
        with connection() as c:
            pid = c.info.backend_pid
            c.execute("UPDATE buyers SET upstream_customer='must-rollback' WHERE id='demo-hotel'")
            raise RuntimeError("test rollback")
    with connection() as c:
        assert c.info.backend_pid == pid
        assert (
            c.execute("SELECT upstream_customer FROM buyers WHERE id='demo-hotel'").fetchone()[
                "upstream_customer"
            ]
            == "123"
        )
        with pytest.raises(Problem) as error:
            with connection():
                pass
        assert error.value.code == "DATABASE_BUSY"
    assert pool().get_stats()["pool_size"] == 1


def test_withdrawals_remain_denials_and_generation_rows_are_bounded(service, agent, request_data):
    data = fixture_facts()
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    try:
        changed = deepcopy(data)
        changed[0]["deleted"] = True
        for i in range(4):
            publish(changed, f"withdrawn-{i}", fingerprint(changed))
        with connection() as c:
            assert (
                c.execute("SELECT count(DISTINCT generation) AS n FROM products").fetchone()["n"]
                <= settings().catalog_generations_to_keep
            )
        assert service.get_product(agent, "464306")["deleted"] is True
        assert service.search_products(agent, SearchRequest(query="464306"))["products"] == []
        revised = service.commit_order(agent, commit(p))
        assert revised["policy_outcome"] == "denied"
        assert "PRODUCT_DELETED" in {r["code"] for r in revised["reasons"]}
        with connection() as c:
            snapshot = c.execute(
                "SELECT snapshot FROM proposal_revisions WHERE proposal_id=%s AND revision=1",
                (p["proposal_id"],),
            ).fetchone()["snapshot"]
        assert snapshot["lines"][0]["product_evidence"]["deleted"] is False
    finally:
        publish(data, "restored-fixtures", fingerprint(data))


def test_file_ingestion_preserves_withdrawal_markers(service, agent, request_data, tmp_path):
    records = [{"id": "464306", "deleted": True}, {"id": "464398", "deleted": False}]
    path = tmp_path / "withdrawn-catalog.json"
    path.write_text(json.dumps(records))
    try:
        result = ingest_file(
            path,
            expected_count=2,
            expected_sha=hashlib.sha256(path.read_bytes()).hexdigest(),
            carry_withdrawn=False,
        )
        assert result["products"] == 2 and result["withdrawn_products"] == 1
        assert service.get_product(agent, "464306")["deleted"] is True
        p = service.prepare_order(agent, PrepareRequest(**request_data))
        codes = {r["code"] for r in p["reasons"]}
        assert p["policy_outcome"] == "denied"
        assert "PRODUCT_DELETED" in codes and "PRODUCT_UNKNOWN" not in codes
    finally:
        data = fixture_facts()
        publish(data, "restored-fixtures", fingerprint(data))


def test_search_snapshot_survives_concurrent_generation_pruning(agent, monkeypatch):
    import aimo.search as search

    data = fixture_facts()
    embed = search.embed

    def publish_during_query(texts, query=False):
        replacement = deepcopy(data[0])
        replacement.update(id="replacement", names={"en": "replacement"}, name="replacement")
        publish([replacement], "concurrent-generation", fingerprint(replacement))
        return embed(texts, query=query)

    monkeypatch.setattr(settings(), "catalog_generations_to_keep", 1)
    monkeypatch.setattr(search, "embed", publish_during_query)
    try:
        result = search.search_products(
            agent, SearchRequest(query="milk", limit=20), strategy="semantic"
        )
        ids = {p["id"] for p in result["products"]}
        assert "464306" in ids and "replacement" not in ids
        with connection() as c:
            assert c.execute("SELECT DISTINCT id FROM products").fetchone()["id"] == "replacement"
    finally:
        publish(data, "restored-fixtures", fingerprint(data))
