"""Shared schema-owner grants for bootstrap and release migrations."""

from psycopg import sql


def configure_runtime_role(conn, role_name):
    role = sql.Identifier(role_name)
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
            role
        )
    )
    conn.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
    )
    conn.execute(sql.SQL("REVOKE ALL ON TABLE schema_migrations FROM {}").format(role))
    # Provisioning authority never belongs to ordinary serving/agent code.
    conn.execute(
        sql.SQL(
            "REVOKE INSERT, UPDATE, DELETE ON buyers,identities,policies,internal_agents FROM {}"
        ).format(role)
    )
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
        conn.execute(
            sql.SQL("DROP TRIGGER IF EXISTS runtime_provisioning_update_guard ON {}").format(table)
        )
        conn.execute(
            sql.SQL(
                "CREATE TRIGGER runtime_provisioning_update_guard BEFORE UPDATE ON {} "
                "FOR EACH ROW EXECUTE FUNCTION runtime_provisioning_update_guard({})"
            ).format(table, sql.Literal(role_name))
        )
        conn.execute(sql.SQL("GRANT UPDATE (id) ON {} TO {}").format(table, role))
