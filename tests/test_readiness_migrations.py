"""/health/ready fails (503) when a database object the code needs from migrations 008 to 014 is
missing, and it does so for the restricted runtime role the deployed API really uses.

The first version read schema_migrations, but configure_runtime_role REVOKEs ALL on that table from
the runtime role, so as the deployed API the read was denied and the check never fired. The probes
now use pg_catalog / to_regclass, readable by every role.

Each case drops one object inside a transaction that is rolled back (PostgreSQL DDL is
transactional), then probes as the owner and as a restricted role built by
aimo.permissions.configure_runtime_role. A fully migrated database stays ready; a probe error or a
denied catalog read reports nothing missing; the 503 body names nothing internal. Fixture mode.
"""

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from aimo import api, schema_state
from aimo.config import settings
from aimo.permissions import configure_runtime_role
from aimo.service import Service

PACKAGED = sorted(
    p.name for p in (Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")
)

# (drop statement, the migration whose object it removes)
DROPS = [
    ("ALTER TABLE conversation_turns DROP COLUMN progress", "022_chat_activity.sql"),
    ("ALTER TABLE conversation_turns DROP COLUMN draft_cart", "023_chat_draft_cart.sql"),


    ("DROP FUNCTION save_buyer_settings(text,integer,jsonb)", "022_buyer_settings.sql"),
    ("ALTER TABLE conversation_messages DROP COLUMN attachments", "020_chat_attachments.sql"),
    ("DROP TRIGGER immutable_orders ON orders", "008_orders_immutable.sql"),
    ("ALTER TABLE products DROP COLUMN withdrawn_since", "009_product_withdrawn_since.sql"),
    ("DROP TABLE meal_authorization_withdrawals", "010_meal_authorization_withdrawals.sql"),
    ("DROP INDEX proposals_buyer_updated", "011_proposal_revision_ordering.sql"),
    ("ALTER TABLE proposals DROP COLUMN updated_at", "011_proposal_revision_ordering.sql"),
    ("DROP TABLE memory_mutations", "012_buyer_user_memory.sql"),
    ("DROP TABLE memories", "012_buyer_user_memory.sql"),
    ("ALTER TABLE conversation_turns DROP COLUMN submitted_by", "012_buyer_user_memory.sql"),
    (
        "ALTER TABLE catalog_generations DROP COLUMN import_profile",
        "012_catalog_import_profile.sql",
    ),
    (
        "ALTER TABLE catalog_generations DROP COLUMN source_product_count",
        "013_catalog_sync_withdrawals.sql",
    ),
    ("DROP VIEW catalog_protected_products", "013_catalog_sync_withdrawals.sql"),
    ("DROP TABLE policy_managers", "014_policy_settings.sql"),
    ("DROP TABLE policy_changes", "014_policy_settings.sql"),
    ("DROP TRIGGER immutable_policy_changes ON policy_changes", "014_policy_settings.sql"),
    ("DROP FUNCTION save_buyer_policy(text,integer,jsonb)", "014_policy_settings.sql"),
    ("ALTER TABLE conversation_messages DROP COLUMN image", "015_recipe_images.sql"),
    ("DROP TABLE recipe_image_jobs", "015_recipe_images.sql"),
    ("DROP TABLE purged_proposals", "018_purge_unfinished_proposals.sql"),
    (
        "DROP TRIGGER immutable_recipe_plan_revisions ON recipe_plan_revisions",
        "019_history_immutability.sql",
    ),
    ("DROP TRIGGER immutable_recipe_versions ON recipe_versions", "019_history_immutability.sql"),
    ("DROP TRIGGER immutable_truncate ON orders", "019_history_immutability.sql"),
    ("DROP TABLE scheduler_identities", "025_scheduled_orders.sql"),
    ("DROP TABLE order_request_cancellations", "025_scheduled_orders.sql"),
    ("DROP TRIGGER sched_auth_guard ON scheduled_authorizations", "025_scheduled_orders.sql"),
    ("DROP TABLE scheduled_run_events", "025_scheduled_orders.sql"),
    ("DROP TABLE scheduled_authorization_events", "025_scheduled_orders.sql"),
    ("DROP TRIGGER scheduled_run_guard ON scheduled_runs", "025_scheduled_orders.sql"),
    (
        "DROP TRIGGER cancellation_no_order ON order_request_cancellations",
        "025_scheduled_orders.sql",
    ),
    (
        "DROP TRIGGER immutable_order_request_cancellations ON order_request_cancellations",
        "025_scheduled_orders.sql",
    ),
    (
        "DROP TRIGGER immutable_scheduled_run_events ON scheduled_run_events",
        "025_scheduled_orders.sql",
    ),
]


@pytest.fixture
def conn():
    """One transaction on the scratch test database, always rolled back."""
    with psycopg.connect(settings().database_url) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


@pytest.fixture
def runtime_role(conn):
    """A disposable restricted role configured exactly like the release Job does."""
    capable = conn.execute(
        "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
    ).fetchone()[0]
    if not capable:
        pytest.skip("The restricted-role cases need CREATEROLE in the test database")
    name = "readiness_runtime_" + uuid4().hex
    conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(name)))
    configure_runtime_role(conn, name)
    return name


def become(conn, role):
    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))


def ready():
    with TestClient(api.create_app(Service())) as http:
        return http.get("/health/ready")


def test_a_fully_migrated_database_is_ready(conn):
    assert len(PACKAGED) >= 15  # 001 to 011, the two 012 files and 013
    assert schema_state.missing_in(conn) == []
    assert schema_state.missing_migrations() == []
    response = ready()
    assert response.status_code == 200 and response.json()["status"] == "ready"


def test_every_packaged_migration_from_008_has_a_probe_manifest_entry():
    """A new migration fails here until its probe is added to schema_state.MANIFEST."""
    shipped = [name for name in PACKAGED if name[:3].isdigit() and int(name[:3]) >= 8]
    assert sorted(shipped) == sorted(schema_state.MANIFEST)


@pytest.mark.parametrize(("statement", "migration"), DROPS)
def test_a_missing_object_is_reported_to_the_owner_role(conn, statement, migration):
    conn.execute(statement)
    assert schema_state.missing_in(conn) == [migration]


@pytest.mark.parametrize(("statement", "migration"), DROPS)
def test_a_missing_object_is_reported_to_the_restricted_runtime_role(
    conn, runtime_role, statement, migration
):
    conn.execute(statement)
    become(conn, runtime_role)
    assert schema_state.missing_in(conn) == [migration]


def test_the_restricted_role_cannot_read_the_ledger_which_is_why_it_is_not_used(conn, runtime_role):
    become(conn, runtime_role)
    conn.execute("SAVEPOINT ledger")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT version FROM schema_migrations")
    conn.execute("ROLLBACK TO SAVEPOINT ledger")
    assert schema_state.missing_in(conn) == []  # and the probes still work when all is present


def test_several_missing_objects_are_reported_together_in_order(conn, runtime_role):
    conn.execute("DROP TABLE meal_authorization_withdrawals")
    conn.execute("ALTER TABLE catalog_generations DROP COLUMN import_profile")
    become(conn, runtime_role)
    assert schema_state.missing_in(conn) == [
        "010_meal_authorization_withdrawals.sql",
        "012_catalog_import_profile.sql",
    ]


def test_a_missing_object_makes_it_not_ready_without_naming_anything(monkeypatch):
    names = ["010_meal_authorization_withdrawals.sql", "012_buyer_user_memory.sql"]
    monkeypatch.setattr(schema_state, "missing_migrations", lambda: names)
    response = ready()
    assert response.status_code == 503
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "SCHEMA_NOT_READY"
    for secret in (*names, "010", "012", "meal_authorization", "memories", "migration_"):
        assert secret not in response.text
    monkeypatch.undo()
    assert ready().status_code == 200


def test_a_probe_error_or_a_denied_catalog_read_reports_nothing_missing(monkeypatch):
    def broken(connection):
        raise psycopg.errors.InsufficientPrivilege("permission denied for catalog")

    monkeypatch.setattr(schema_state, "missing_in", broken)
    assert schema_state.missing_migrations() == []
    assert ready().status_code == 200

    def unreachable():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(schema_state, "connection", unreachable)
    assert schema_state.missing_migrations() == []
