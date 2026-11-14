"""Lock order of the purchasing transactions (CNF-005) and agent identities having no session
(CNF-003). Fixture catalog and invented FixtureClient prices only; orders are mock acceptance.
"""

import os
import re
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.api import create_app
from aimo.db import connection, now
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest

RANK = {"buyers": 0, "identities": 1, "proposals": 2}


@pytest.fixture
def actor(buyer):
    return auth.internal_agent(buyer)


@pytest.fixture
def lock_log(monkeypatch):
    """Every row-locking statement the application sends, in order, as the table it locks."""
    seen = []
    real = psycopg.Connection.execute

    def execute(self, query, *args, **kwargs):
        text = query if isinstance(query, str) else query.as_string(self)
        found = re.search(r"\bFROM\s+(\w+)\b.*\bFOR (UPDATE|SHARE)\b", text, re.S)
        if found:
            seen.append(found.group(1))
        return real(self, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", execute)
    return seen


def transactions(log):
    """Split the lock log into purchasing transactions: each starts by locking the buyer."""
    chunks = []
    for table in log:
        if table == "buyers":
            chunks.append([])
        assert chunks, f"{table} was locked before the buyer lock"
        chunks[-1].append(table)
    return chunks


# --- JNP3-CNF-005: the buyer is locked first, then identities, then the proposal ---------------


def test_purchasing_transactions_lock_buyer_then_identities_then_proposal(
    service, buyer, actor, lock_log, mission
):
    p = service.prepare_order(actor, mission)  # prepare, then a decision, then confirm and commit
    workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=1, decision="approve")
    )
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    assert (
        conversations.confirm(buyer, p["proposal_id"], body, service)["status"] == "accepted_mock"
    )
    chunks = transactions(lock_log)
    assert len(chunks) >= 4
    for chunk in chunks:
        ranks = [RANK[t] for t in chunk]
        assert ranks == sorted(ranks), f"locks out of order: {chunk}"
    # The decision, the confirmation and the commit each lock all three, in that order.
    assert sum(chunk == ["buyers", "identities", "proposals"] for chunk in chunks) >= 3


# --- JNP3-CNF-003: an agent identity cannot sign in or hold a session ----------------------------


def post_login(client, username, password):
    return client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": username, "password": password},
    )


def forged_cookie(identity_id):
    token, csrf = uuid4().hex, uuid4().hex
    with connection() as c:
        c.execute(
            "INSERT INTO sessions VALUES(%s,%s,%s,%s)",
            (auth.digest(token), identity_id, auth.digest(csrf), now() + timedelta(hours=1)),
        )
    return auth.signer().dumps({"token": token, "csrf": csrf}), csrf


def test_agent_identities_cannot_log_in(service, agent, actor):
    client = TestClient(create_app(service))
    for username in (agent["id"], actor["id"]):
        for password in (os.environ["DEMO_BUYER_PASSWORD"], "anything-else"):
            result = post_login(client, username, password)
            assert result.status_code == 401 and "LOGIN_FAILED" in result.text
    assert post_login(client, "buyer", os.environ["DEMO_BUYER_PASSWORD"]).status_code == 200


def test_a_session_row_for_an_agent_identity_authenticates_nothing(
    service, buyer, agent, actor, request_data
):
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    path = f"/api/purchases/{p['proposal_id']}/confirm"
    payload = {"proposal_id": p["proposal_id"], "revision": 1, "idempotency_key": str(uuid4())}
    # Control: the same forged-session mechanism works for the real approver.
    cookie, csrf = forged_cookie(buyer["id"])
    with TestClient(create_app(service)) as client:
        client.cookies.set("aimo_session", cookie)
        assert client.get("/api/purchases").status_code == 200
    for identity in (agent, actor):
        cookie, csrf = forged_cookie(identity["id"])
        with TestClient(create_app(service)) as client:
            client.cookies.set("aimo_session", cookie)
            headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
            assert client.get("/api/purchases").status_code == 401
            denied = client.post(path, headers=headers, json=payload)
            assert denied.status_code == 401 and "UNAUTHENTICATED" in denied.text
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 0
