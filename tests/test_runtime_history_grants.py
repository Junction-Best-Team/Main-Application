"""The runtime role holds no UPDATE or DELETE on the history tables (owner decision Q-99).

The history tables are guarded by triggers; this adds the privilege layer so that the role the
deployed API uses cannot even attempt to change or delete them, and cannot write purged_proposals.
Only the schema owner purges (operator command `aimo purge-proposals` with the owner's
DATABASE_URL, not scheduled). Tables the app really updates or deletes keep their privileges.
Every case builds the role with aimo.permissions.configure_runtime_role in a rolled-back
transaction on the scratch test database.
"""

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from aimo.config import settings
from aimo.permissions import HISTORY_TABLES, configure_runtime_role

# Pure history: the app only inserts into and reads these (no UPDATE, DELETE or row lock anywhere
# in src); the triggers already refuse changes.
APPEND_ONLY = (
    "proposal_revisions",
    "audit_events",
    "customer_confirmations",
    "meal_authorization_withdrawals",
    "orders",
    "recipe_plan_revisions",
    "recipe_versions",
    # WS-E: the scheduler's logs and the cancellations only ever INSERT (scheduler.run_event,
    # scheduler.auth_event, schedules.event, cancellations.cancel_request) and SELECT.
    "scheduled_run_events",
    "scheduled_authorization_events",
    "order_request_cancellations",
)
# The app updates these (status, links, locks) so they keep UPDATE and DELETE as before.
APP_WRITES = (
    "proposals",
    "approvals",
    "prepare_requests",
    "recipe_plans",
    "conversation_messages",
    "scheduled_authorizations",  # status, next run date, pause (the triggers guard the terms)
    "scheduled_runs",  # the run's state machine
)


@pytest.fixture
def role_conn():
    with psycopg.connect(settings().database_url) as conn:
        capable = conn.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]
        if not capable:
            pytest.skip("The restricted-role cases need CREATEROLE in the test database")
        role = "history_grants_" + uuid4().hex
        try:
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            configure_runtime_role(conn, role)
            configure_runtime_role(conn, role)  # twice, as the release Job does on every release
            yield conn, role
        finally:
            conn.rollback()


def has(conn, role, table, privilege):
    return conn.execute(
        "SELECT has_table_privilege(%s,%s,%s)", (role, table, privilege)
    ).fetchone()[0]


def test_the_history_table_list_names_exactly_the_append_only_tables_and_purged_proposals():
    assert set(HISTORY_TABLES) == set(APPEND_ONLY) | {"purged_proposals"}


@pytest.mark.parametrize("table", APPEND_ONLY + ("purged_proposals", "policies", "policy_changes"))
def test_the_runtime_role_holds_no_update_delete_or_truncate_on_history(role_conn, table):
    conn, role = role_conn
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        assert not has(conn, role, table, privilege), (table, privilege)
    assert has(conn, role, table, "SELECT")


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_the_runtime_role_still_appends_to_the_history_it_writes(role_conn, table):
    conn, role = role_conn
    assert has(conn, role, table, "INSERT"), table


def test_only_the_owner_writes_purged_proposals(role_conn):
    conn, role = role_conn
    assert not has(conn, role, "purged_proposals", "INSERT")
    assert has(conn, role, "purged_proposals", "SELECT")


@pytest.mark.parametrize("table", APP_WRITES)
def test_tables_the_app_updates_keep_their_privileges(role_conn, table):
    conn, role = role_conn
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert has(conn, role, table, privilege), (table, privilege)
