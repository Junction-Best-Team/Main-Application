"""PER-002: TRUNCATE of the history tables is refused unless the session says it is intended.

immutable_record() is a row trigger and PostgreSQL does not fire row triggers for TRUNCATE, so the
schema owner could erase history. Migration 019 adds a statement-level BEFORE TRUNCATE guard to
the history tables; a deliberate reset (the test fixtures, a development reset) sets the
transaction-local `aimo.allow_history_truncate = 'on'` first. Design: evidence/ws-c/per-002-truncate-design.md.
The runtime role never held TRUNCATE; permissions.py now also revokes it defensively.
Every case runs in a rolled-back transaction on the scratch test database.
"""

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from aimo.config import settings
from aimo.permissions import configure_runtime_role

GUARDED = (
    "proposal_revisions",
    "audit_events",
    "policies",
    "customer_confirmations",
    "orders",
    "meal_authorization_withdrawals",
    "purged_proposals",
)


@pytest.fixture
def conn():
    with psycopg.connect(settings().database_url) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


@pytest.mark.parametrize("table", GUARDED)
def test_truncate_is_refused_without_the_setting_and_allowed_with_it(conn, table):
    statement = sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table))
    conn.execute("SAVEPOINT guard")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
        conn.execute(statement)
    conn.execute("ROLLBACK TO SAVEPOINT guard")
    conn.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
    conn.execute(statement)  # now deliberate


def test_a_cascade_from_buyers_is_refused_too_and_the_fixture_pattern_works(conn):
    reset = "TRUNCATE buyers, login_attempts, purged_proposals RESTART IDENTITY CASCADE"
    conn.execute("SAVEPOINT cascade")
    with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
        conn.execute(reset)
    conn.execute("ROLLBACK TO SAVEPOINT cascade")
    conn.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
    conn.execute(reset)
    assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0


def test_the_setting_is_transaction_local_and_must_be_exactly_on():
    with psycopg.connect(settings().database_url) as first:
        first.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        first.rollback()
        first.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.RaiseException):
            first.execute(
                "TRUNCATE audit_events"
            )  # the earlier SET LOCAL ended with its transaction
        first.execute("ROLLBACK TO SAVEPOINT s")
        for value in ("off", "yes", "true", ""):
            first.execute("SET LOCAL aimo.allow_history_truncate = " + f"'{value}'")
            with pytest.raises(psycopg.errors.RaiseException):
                first.execute("TRUNCATE audit_events")
            first.execute("ROLLBACK TO SAVEPOINT s")
        first.rollback()


def test_the_catalog_shows_a_statement_level_truncate_guard_on_each_table(conn):
    rows = conn.execute(
        """SELECT c.relname, t.tgenabled, t.tgtype FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid
        WHERE p.proname='immutable_truncate_guard' AND NOT t.tgisinternal"""
    ).fetchall()
    assert {r[0] for r in rows} == set(GUARDED)
    for _, enabled, tgtype in rows:
        # bits: 1 row-level must be clear, 2 BEFORE, 32 TRUNCATE
        assert enabled == "O" and tgtype & (1 | 2 | 32) == (2 | 32)


def test_the_runtime_role_loses_a_truncate_grant_when_the_release_job_reapplies_grants(conn):
    capable = conn.execute(
        "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
    ).fetchone()[0]
    if not capable:
        pytest.skip("The restricted-role case needs CREATEROLE in the test database")
    role = "truncate_guard_" + uuid4().hex
    conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
    conn.execute(
        sql.SQL("GRANT TRUNCATE, REFERENCES, TRIGGER ON audit_events TO {}").format(
            sql.Identifier(role)
        )
    )
    assert conn.execute(
        "SELECT has_table_privilege(%s,'audit_events','TRUNCATE')", (role,)
    ).fetchone()[0]
    configure_runtime_role(conn, role)
    for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'audit_events',%s)", (role, privilege)
        ).fetchone()[0]
