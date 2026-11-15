import os
from datetime import timedelta
from functools import cache
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

# Tests only touch this dedicated database. Never clear the development catalog.
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql://aimo:aimo@localhost:55432/aimo_test"
)
os.environ["EMBEDDING_BACKEND"] = "fixture"
os.environ["UPSTREAM_MODE"] = "fixture"
os.environ["APPROVAL_SESSION_SECRET"] = "test-session-secret-only-not-a-real-secret-12345678"
os.environ["SECURE_COOKIES"] = "false"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["DEMO_BUYER_PASSWORD"] = "test-buyer-password-only"
# Tests never reach the semantic classifier; guardrail tests inject explicit fakes.
os.environ["GUARDRAIL_MODE"] = "off"
# Existing authored chat transcripts use the OpenAI-compatible transport.
# Native Google adapters have separate mocked contract and integration coverage.
os.environ["LLM_PROVIDER"] = "openrouter"
os.environ["GUARDRAIL_PROVIDER"] = "openrouter"
os.environ["GEMINI_API_KEY"] = ""

from supplier_fixture import FixtureClient, install

from aimo.cli import migrate, seed
from aimo.config import settings
from aimo.db import connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import publish
from aimo.scheduler import helsinki_today
from aimo.schemas import PrepareRequest
from aimo.service import Service

install()


@pytest.fixture(scope="session", autouse=True)
def database():
    settings.cache_clear()
    url = urlsplit(os.environ["DATABASE_URL"])
    name = url.path.lstrip("/")
    if not name.endswith("_test"):
        raise RuntimeError("Test database name must end in _test")
    with psycopg.connect(urlunsplit(url._replace(path="/postgres")), autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    migrate()
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


@pytest.fixture(scope="session")
def fixture_password_hasher():
    from aimo.auth import hasher

    # Reuse a real Argon2 hash during fixture setup instead of recomputing it
    # thousands of times. Tests of seed() and login still use the real hasher.
    return SimpleNamespace(hash=cache(hasher.hash))


@pytest.fixture(autouse=True)
def reset_buyers(monkeypatch, fixture_password_hasher):
    with connection() as c:
        # The history tables refuse TRUNCATE unless the transaction says it is a deliberate reset.
        c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        c.execute("TRUNCATE buyers,login_attempts,purged_proposals RESTART IDENTITY CASCADE")
    with monkeypatch.context() as patch:
        patch.setattr("aimo.cli.hasher", fixture_password_hasher)
        seed()


@pytest.fixture
def agent():
    with connection() as c:
        return c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()


@pytest.fixture
def buyer():
    with connection() as c:
        return c.execute("SELECT * FROM identities WHERE id='buyer'").fetchone()


@pytest.fixture
def confirm_terms(buyer):
    """Record the buyer's confirmation of one exact proposal revision, as `conversations.confirm`
    does, but without approving or committing, so a test can drive the agent's commit itself."""

    def record(p, revision=None, actor_id=None):
        from aimo import approval_workflow as workflow

        revision = revision or p["revision"]
        with connection() as c:
            r = c.execute(
                "SELECT fingerprint FROM proposal_revisions WHERE proposal_id=%s AND revision=%s",
                (p["proposal_id"], revision),
            ).fetchone()
            c.execute(
                """INSERT INTO customer_confirmations(proposal_id,revision,fingerprint,actor_id,key,buyer_id)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    p["proposal_id"],
                    revision,
                    r["fingerprint"],
                    actor_id or buyer["id"],
                    str(uuid4()),
                    buyer["buyer_id"],
                ),
            )
            workflow.audit(
                c,
                p["proposal_id"],
                actor_id or buyer["id"],
                "customer_confirmed",
                {"revision": revision},
            )

    return record


@pytest.fixture
def connector():
    return FixtureClient()


@pytest.fixture
def service(connector):
    return Service(connector)


@pytest.fixture
def request_data():
    return {
        "request_id": "Hotel breakfast",
        "idempotency_key": str(uuid4()),
        "destination": "hotel-helsinki",
        "delivery_date": str(helsinki_today() + timedelta(days=2)),
        "requirements": {"lactose_free": True},
        "lines": [{"product_id": "464306", "amount": "10", "unit": "L"}],
    }


@pytest.fixture
def mission(request_data):
    request_data["lines"] = [
        {"product_id": "464306", "amount": "600", "unit": "L"},
        {"product_id": "464398", "amount": "400", "unit": "L", "substitutes_for": "464306"},
    ]
    return PrepareRequest.model_validate(request_data)


@pytest.fixture
def placed_order(service, buyer, request_data):
    """A placed mock order of the demo buyer (milk, 10 L): the source of a standing order."""
    from aimo import auth, conversations
    from aimo.schemas import CommitRequest

    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    receipt = conversations.confirm(buyer, p["proposal_id"], body, service)
    return {"order_id": receipt["order_id"], "proposal_id": p["proposal_id"]}


@pytest.fixture
def demo_mode(monkeypatch):
    """Scheduler demo mode (CNF-038): a first run date of today is allowed."""
    from aimo.config import settings

    monkeypatch.setattr(settings(), "scheduler_demo_mode", True)
