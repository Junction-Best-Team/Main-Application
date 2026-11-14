from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from aimo.config import settings
from aimo.permissions import configure_runtime_role


def test_runtime_can_lock_buyers_and_identities_without_provisioning_rights():
    role_name = "runtime_permissions_test_" + uuid4().hex
    with psycopg.connect(settings().database_url) as conn:
        capabilities = conn.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]
        if not capabilities:
            pytest.skip("Restricted-role integration test requires CREATEROLE in the test database")
        try:
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role_name)))
            # Repeated release grants cover newly created tables and sequences.
            conn.execute("CREATE TABLE release_grants_test (id bigserial PRIMARY KEY, value text)")
            configure_runtime_role(conn, role_name)
            configure_runtime_role(conn, role_name)
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name)))
            assert (
                conn.execute(
                    "INSERT INTO release_grants_test(value) VALUES('runtime') RETURNING id"
                ).fetchone()[0]
                == 1
            )
            conn.execute("UPDATE release_grants_test SET value='updated'")
            assert conn.execute("SELECT value FROM release_grants_test").fetchone()[0] == "updated"
            conn.execute("DELETE FROM release_grants_test")
            assert conn.execute("SELECT id FROM buyers FOR UPDATE").fetchone()
            assert conn.execute("SELECT id FROM identities FOR SHARE").fetchone()
            for statement in (
                "UPDATE buyers SET id=id",
                "UPDATE identities SET id=id",
                "UPDATE buyers SET current_policy=current_policy",
                "UPDATE identities SET authority=authority",
                "UPDATE policies SET rules=rules",
                "UPDATE internal_agents SET identity_id=identity_id",
                "INSERT INTO buyers VALUES ('forbidden','123',1)",
                "DELETE FROM identities",
                "SELECT * FROM schema_migrations",
                "CREATE TABLE forbidden_schema_change(id int)",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with conn.transaction():
                        conn.execute(statement)
            assert conn.execute("SELECT id FROM buyers FOR UPDATE").fetchone()
            conn.execute("RESET ROLE")
            assert conn.execute("UPDATE buyers SET id=id").rowcount > 0
            assert conn.execute("UPDATE identities SET authority=authority").rowcount > 0
        finally:
            # The disposable role, grants and triggers must never escape this test.
            conn.rollback()
