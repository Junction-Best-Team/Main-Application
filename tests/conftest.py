import os
from datetime import date, timedelta
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
os.environ["GUARDRAIL_API_KEY"] = ""

from aimo.cli import migrate, seed
from aimo.config import settings
from aimo.db import connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import publish
from aimo.schemas import PrepareRequest
from aimo.service import Service
from aimo.upstream import FixtureClient


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


@pytest.fixture(autouse=True)
def reset_buyers():
    with connection() as c:
        c.execute("TRUNCATE buyers,login_attempts RESTART IDENTITY CASCADE")
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
        "delivery_date": str(date.today() + timedelta(days=2)),
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
