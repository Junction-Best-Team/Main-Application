"""Run inside the PR #4 image, only as an explicit Terraform setup Job."""

import os
from pathlib import Path

from psycopg import sql

from aimo.cli import migrate, seed
from aimo.config import settings
from aimo.db import connection
from aimo.ingest import download, ingest_file


def configure_runtime_role(conn, role_name):
    role = sql.Identifier(role_name)
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(role)
    )
    conn.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
    )
    conn.execute(sql.SQL("REVOKE ALL ON TABLE schema_migrations FROM {}").format(role))
    # Provisioning authority never belongs to ordinary serving/agent code.
    conn.execute(sql.SQL(
        "REVOKE INSERT, UPDATE, DELETE ON buyers,identities,policies,internal_agents FROM {}"
    ).format(role))
    # PostgreSQL requires UPDATE privilege on at least one column for SELECT
    # FOR UPDATE/FOR SHARE. Grant only the identifier column, then reject actual
    # runtime updates before they happen; locks do not fire UPDATE triggers.
    conn.execute("""
        CREATE OR REPLACE FUNCTION runtime_provisioning_update_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user = TG_ARGV[0] THEN
                RAISE EXCEPTION 'Runtime provisioning updates are forbidden'
                    USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    for table_name in ("buyers", "identities"):
        table = sql.Identifier(table_name)
        conn.execute(sql.SQL("DROP TRIGGER IF EXISTS runtime_provisioning_update_guard ON {}").format(table))
        conn.execute(sql.SQL(
            "CREATE TRIGGER runtime_provisioning_update_guard BEFORE UPDATE ON {} "
            "FOR EACH ROW EXECUTE FUNCTION runtime_provisioning_update_guard({})"
        ).format(table, sql.Literal(role_name)))
        conn.execute(sql.SQL("GRANT UPDATE (id) ON {} TO {}").format(table, role))


def main():
    runtime_url = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = os.environ.pop("BOOTSTRAP_DATABASE_URL")
    settings.cache_clear()
    migrate()  # doadmin can enable pgvector; ordinary serving credentials cannot.
    seed()  # Inserts missing demo rules/identities; never overwrites credentials.
    with connection() as conn:
        configure_runtime_role(conn, os.environ["RUNTIME_DATABASE_USER"])

    # Import with the same restricted role and pinned model used by the app.
    os.environ["DATABASE_URL"] = runtime_url
    settings.cache_clear()
    catalog = Path("/tmp/valio_aimo_junction26_product_data.json")
    download(catalog)
    ingest_file(catalog)
    print("Database setup and verified full-catalog import completed.")


if __name__ == "__main__":
    main()
