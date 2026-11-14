"""PER-002: the restricted runtime role must not hold TRUNCATE on history tables.

PostgreSQL's immutable_record() row trigger never fires for TRUNCATE (see the strict xfails
in test_additive_migrations.py), so the only thing keeping the application from erasing
history this way is the missing TRUNCATE privilege. This pins that fact against the role
that aimo.permissions.configure_runtime_role actually builds.
"""

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from aimo.config import settings
from aimo.permissions import configure_runtime_role

HISTORY = (
    "proposal_revisions",
    "audit_events",
    "policies",
    "customer_confirmations",
    "orders",
    "meal_authorization_withdrawals",
)
PROVISIONING = ("buyers", "identities")


@pytest.fixture
def runtime_role_conn():
    """A connection inside one transaction, with a disposable runtime role configured.

    The role, its grants and the helper triggers are rolled back, never committed.
    """
    role_name = "runtime_truncate_test_" + uuid4().hex
    with psycopg.connect(settings().database_url) as conn:
        capabilities = conn.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]
        if not capabilities:
            pytest.skip("Restricted-role integration test requires CREATEROLE in the test database")
        try:
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role_name)))
            # Twice, as release Jobs do: repeated grants must not add TRUNCATE either.
            configure_runtime_role(conn, role_name)
            configure_runtime_role(conn, role_name)
            yield conn, role_name
        finally:
            conn.rollback()


@pytest.mark.parametrize("table", HISTORY + PROVISIONING)
def test_runtime_role_cannot_truncate(runtime_role_conn, table):
    conn, role_name = runtime_role_conn
    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name)))
    for statement in (
        f"TRUNCATE {table}",
        f"TRUNCATE TABLE ONLY {table}",
        f"TRUNCATE {table} CASCADE",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute(statement)
    # Sanity: the role is otherwise working, so the refusals above are about TRUNCATE alone.
    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= 0


def test_runtime_role_truncate_not_granted_by_any_path(runtime_role_conn):
    """Catalog view of the same fact: no owner, membership, PUBLIC or default-ACL route."""
    conn, role_name = runtime_role_conn
    for table in HISTORY + PROVISIONING:
        assert not conn.execute(
            "SELECT has_table_privilege(%s, %s, 'TRUNCATE')", (role_name, table)
        ).fetchone()[0], table
    # Not the owner of any public table (owners may TRUNCATE without a grant).
    assert not conn.execute(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner=%s", (role_name,)
    ).fetchone()
    # No inherited membership (e.g. pg_write_all_data does not include TRUNCATE, but a
    # table-owning group role would).
    assert not conn.execute(
        "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid "
        "WHERE m.member=(SELECT oid FROM pg_roles WHERE rolname=%s)",
        (role_name,),
    ).fetchone()
    # No PUBLIC grant (grantee oid 0) of TRUNCATE on any public table.
    public_acls = conn.execute(
        "SELECT c.relname FROM pg_class c, aclexplode(c.relacl) x "
        "WHERE c.relkind='r' AND c.relnamespace='public'::regnamespace "
        "AND x.grantee=0 AND x.privilege_type='TRUNCATE'"
    ).fetchall()
    assert public_acls == []
    # No default privileges that would hand TRUNCATE to future tables.
    assert not conn.execute(
        "SELECT 1 FROM pg_default_acl d, aclexplode(d.defaclacl) x "
        "WHERE x.privilege_type='TRUNCATE'"
    ).fetchone()


def test_truncate_check_is_discriminating(runtime_role_conn):
    """Positive control: an explicit TRUNCATE grant flips the result, so the refusals above
    really come from the missing privilege and not from some unrelated failure."""
    conn, role_name = runtime_role_conn
    role = sql.Identifier(role_name)
    conn.execute(sql.SQL("GRANT TRUNCATE ON audit_events TO {}").format(role))
    conn.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
    conn.execute("TRUNCATE audit_events")  # succeeds because it was granted; rolled back
    assert conn.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0
