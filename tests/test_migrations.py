"""Real PostgreSQL transactions/locks; each synthetic migration uses a private schema."""

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from aimo import cli
from aimo.config import settings


@pytest.fixture
def migration_area(tmp_path, monkeypatch):
    schema = "migration_test_" + uuid4().hex
    application = schema
    with psycopg.connect(settings().database_url) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    directory = tmp_path / "migrations"
    directory.mkdir()

    @contextmanager
    def connection():
        with psycopg.connect(settings().database_url, application_name=application) as conn:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            yield conn

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "connection", connection)
    try:
        yield directory, connection, application
    finally:
        with psycopg.connect(settings().database_url) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_pending_migrations_apply_once_and_reruns_skip(migration_area, capsys):
    directory, connection, _ = migration_area
    # Same numeric prefix is supported; the full filename is the ledger key.
    (directory / "004_a.sql").write_text("CREATE TABLE applied (id bigserial PRIMARY KEY)")
    (directory / "004_b.sql").write_text("INSERT INTO applied DEFAULT VALUES")
    cli.migrate()
    cli.migrate()
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM applied").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
    assert "Skipping applied migration 004_a.sql" in capsys.readouterr().out


def test_concurrent_migrations_wait_for_same_database_lock(migration_area):
    directory, connection, application = migration_area
    (directory / "future.sql").write_text(
        "CREATE TABLE applied (id int); INSERT INTO applied VALUES(1)"
    )
    with connection() as blocker, ThreadPoolExecutor(max_workers=2) as executor:
        blocker.execute("SELECT pg_advisory_xact_lock(893018)")
        attempts = [executor.submit(cli.migrate) for _ in range(2)]
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with psycopg.connect(settings().database_url) as observer:
                    waiting = observer.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name=%s AND wait_event='advisory'",
                        (application,),
                    ).fetchone()[0]
                if waiting == 2:
                    break
                time.sleep(0.02)
            assert waiting == 2, "Both migration connections should wait on the advisory lock"
            assert not any(attempt.done() for attempt in attempts)
        finally:
            blocker.commit()
        for attempt in attempts:
            attempt.result(timeout=5)
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM applied").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1


def test_failure_rolls_back_ddl_and_ledger_and_allows_retry(migration_area):
    directory, connection, _ = migration_area
    (directory / "future.sql").write_text("CREATE TABLE applied (id int); SELECT 1/0")
    with pytest.raises(psycopg.errors.DivisionByZero):
        cli.migrate()
    with connection() as conn:
        assert conn.execute("SELECT to_regclass('applied')").fetchone()[0] is None
        assert conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0] is None
    (directory / "future.sql").write_text("CREATE TABLE applied (id int)")
    cli.migrate()


def test_grant_failure_rolls_back_migration(migration_area, monkeypatch):
    from aimo import permissions

    directory, connection, _ = migration_area
    (directory / "future.sql").write_text("CREATE TABLE applied (id int)")

    def fail_grants(conn, role):
        raise RuntimeError("synthetic grant failure")

    monkeypatch.setattr(permissions, "configure_runtime_role", fail_grants)
    with pytest.raises(RuntimeError, match="synthetic grant failure"):
        cli.migrate(runtime_role="synthetic_runtime")
    with connection() as conn:
        assert conn.execute("SELECT to_regclass('applied')").fetchone()[0] is None


def test_missing_packaged_migrations_fail_closed(migration_area):
    _, connection, _ = migration_area
    with pytest.raises(RuntimeError, match="No packaged migration files"):
        cli.migrate()
    with connection() as conn:
        assert conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0] is None


@pytest.mark.parametrize("checkpoint", ["005_hosted_search.sql", "005_recipe_planning.sql"])
def test_packaged_migrations_upgrade_populated_database(migration_area, monkeypatch, checkpoint):
    from pathlib import Path

    directory, private_connection, schema = migration_area
    packaged = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))

    @contextmanager
    def connection():
        with private_connection() as c:
            # Reuse the database's installed pgvector extension; all tables stay private.
            c.execute(sql.SQL("SET search_path TO {},public").format(sql.Identifier(schema)))
            yield c

    monkeypatch.setattr(cli, "connection", connection)
    for path in packaged:
        if path.name <= checkpoint:
            (directory / path.name).write_text(path.read_text())
    cli.migrate()
    pid, order_id, plan_id = uuid4(), uuid4(), uuid4()
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('buyer','123',1)")
        c.execute("INSERT INTO identities VALUES('agent','buyer','agent',true,'test','{}')")
        c.execute(
            "INSERT INTO proposals(id,buyer_id,agent_id,current_revision,order_id) VALUES(%s,'buyer','agent',1,%s)",
            (pid, order_id),
        )
        request = (
            '{"recipe_plan_id":"' + str(plan_id) + '"}'
            if checkpoint == "005_recipe_planning.sql"
            else "{}"
        )
        c.execute(
            "INSERT INTO proposal_revisions VALUES(%s,1,1,%s,'{}','fingerprint','approval_required','[]','[]',now())",
            (pid, request),
        )
        c.execute(
            "INSERT INTO approvals(id,proposal_id,revision,status,fingerprint) VALUES(%s,%s,1,'approved','fingerprint')",
            (uuid4(), pid),
        )
        c.execute("INSERT INTO orders VALUES(%s,%s,'buyer',1,'{}','2026-01-01Z')", (order_id, pid))
        c.execute(
            "INSERT INTO audit_events(proposal_id,actor_id,event,detail) VALUES(%s,'agent','proposal_prepared','{}')",
            (pid,),
        )
        c.execute(
            "INSERT INTO prepare_requests VALUES('buyer','agent','original-key','hash',%s)", (pid,)
        )
        if checkpoint == "005_recipe_planning.sql":
            c.execute("INSERT INTO recipes VALUES('recipe')")
            c.execute(
                "INSERT INTO recipe_versions(recipe_id,version,data,source,source_version,source_hash,attribution,license) VALUES('recipe','v1','{}','test','v1','hash','test','test')"
            )
            c.execute(
                "INSERT INTO recipe_plans(id,buyer_id,agent_id,turn_id,recipe_id,recipe_version,portions,locked) VALUES(%s,'buyer','agent','turn','recipe','v1',200,true)",
                (plan_id,),
            )
            c.execute("INSERT INTO recipe_plan_revisions VALUES(%s,1,'{}',now())", (plan_id,))
        before = c.execute(
            "SELECT * FROM proposal_revisions WHERE proposal_id=%s", (pid,)
        ).fetchone()
    for path in packaged:
        (directory / path.name).write_text(path.read_text())
    cli.migrate()
    cli.migrate()
    with connection() as c:
        assert c.execute(
            "SELECT current_revision,order_id FROM proposals WHERE id=%s", (pid,)
        ).fetchone() == (1, order_id)
        assert (
            c.execute("SELECT * FROM proposal_revisions WHERE proposal_id=%s", (pid,)).fetchone()
            == before
        )
        assert c.execute(
            "SELECT status FROM approvals WHERE proposal_id=%s", (pid,)
        ).fetchone() == ("approved",)
        assert c.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(packaged)
        c.execute(
            "INSERT INTO prepare_requests VALUES('buyer','agent','fresh-key','hash',%s)", (pid,)
        )
        assert (
            c.execute(
                "SELECT count(*) FROM prepare_requests WHERE proposal_id=%s", (pid,)
            ).fetchone()[0]
            == 2
        )
        if checkpoint == "005_recipe_planning.sql":
            assert c.execute(
                "SELECT proposal_id,locked FROM recipe_plans WHERE id=%s", (plan_id,)
            ).fetchone() == (pid, True)


@pytest.mark.parametrize("previous_008", [False, True])
def test_purchase_ordering_migration_uses_latest_revision_audit(migration_area, previous_008):
    from pathlib import Path

    directory, connection, _ = migration_area
    (directory / "001_prior.sql").write_text("""
        CREATE TABLE proposals (id uuid PRIMARY KEY, buyer_id text, created_at timestamptz);
        CREATE TABLE audit_events (proposal_id uuid, event text, created_at timestamptz);
    """)
    cli.migrate()
    old, revised = uuid4(), uuid4()
    with connection() as c:
        c.execute(
            "INSERT INTO proposals VALUES(%s,'buyer','2026-01-01Z'),(%s,'buyer','2026-01-01Z')",
            (old, revised),
        )
        c.execute(
            """INSERT INTO audit_events VALUES
            (%s,'proposal_prepared','2026-01-01Z'),
            (%s,'proposal_revised','2026-01-02Z'),
            (%s,'approval_rejected','2026-01-03Z')""",
            (revised, revised, revised),
        )
    if previous_008:
        # Reproduce a DB that applied the old filename, then advanced its terms.
        old_file = directory / "008_proposal_revision_ordering.sql"
        old_file.write_text("""
            ALTER TABLE proposals ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
            UPDATE proposals SET updated_at=created_at;
            CREATE INDEX proposals_buyer_updated ON proposals(buyer_id,updated_at DESC,id);
        """)
        cli.migrate()
        old_file.unlink()
        with connection() as c:
            c.execute("UPDATE proposals SET updated_at='2026-01-04Z' WHERE id=%s", (revised,))
    source = Path(__file__).resolve().parents[1] / "migrations/011_proposal_revision_ordering.sql"
    (directory / source.name).write_text(source.read_text())
    cli.migrate()
    cli.migrate()
    with connection() as c:
        assert c.execute(
            "SELECT id,updated_at=created_at FROM proposals ORDER BY updated_at DESC"
        ).fetchall() == [(revised, False), (old, True)]
        assert c.execute(
            "SELECT updated_at=%s::timestamptz FROM proposals WHERE id=%s",
            ("2026-01-04Z" if previous_008 else "2026-01-02Z", revised),
        ).fetchone()[0]
        if previous_008:
            assert c.execute(
                "SELECT 1 FROM schema_migrations WHERE version='008_proposal_revision_ordering.sql'"
            ).fetchone()
    if previous_008:
        # Person 3's lower-numbered migration can arrive after 011 is applied.
        (directory / "008_customer_policy_edits.sql").write_text(
            "CREATE TABLE recorded_policy_edits (id integer PRIMARY KEY)"
        )
        cli.migrate()
        cli.migrate()
        with connection() as c:
            assert c.execute("SELECT to_regclass('recorded_policy_edits')").fetchone()[0]
            assert (
                c.execute(
                    "SELECT count(*) FROM schema_migrations WHERE version LIKE '008_%'"
                ).fetchone()[0]
                == 2
            )


@pytest.mark.parametrize("duplicate", [False, True])
def test_recipe_proposal_link_backfills_or_rejects_ambiguous_history(migration_area, duplicate):
    from pathlib import Path

    directory, connection, _ = migration_area
    (directory / "001_prior.sql").write_text("""
        CREATE TABLE proposals (id uuid PRIMARY KEY, buyer_id text, agent_id text, current_revision int);
        CREATE TABLE recipe_plans (id uuid PRIMARY KEY, buyer_id text, agent_id text, locked boolean);
        CREATE TABLE proposal_revisions (proposal_id uuid, revision int, request jsonb);
    """)
    cli.migrate()
    plan_id, proposal_id = uuid4(), uuid4()
    with connection() as c:
        c.execute("INSERT INTO recipe_plans VALUES(%s,'buyer','agent',false)", (plan_id,))
        for pid in [proposal_id] + ([uuid4()] if duplicate else []):
            c.execute("INSERT INTO proposals VALUES(%s,'buyer','agent',1)", (pid,))
            c.execute(
                "INSERT INTO proposal_revisions VALUES(%s,1,jsonb_build_object('recipe_plan_id',%s::text))",
                (pid, str(plan_id)),
            )
    source = Path(__file__).resolve().parents[1] / "migrations/006_recipe_proposal_link.sql"
    (directory / source.name).write_text(source.read_text())
    if duplicate:
        with pytest.raises(psycopg.errors.RaiseException, match="multiple proposals"):
            cli.migrate()
        with connection() as c:
            assert not c.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='recipe_plans' AND column_name='proposal_id'"
            ).fetchone()
    else:
        cli.migrate()
        cli.migrate()
        with connection() as c:
            assert c.execute("SELECT proposal_id,locked FROM recipe_plans").fetchone() == (
                proposal_id,
                True,
            )


def test_memory_migration_upgrades_populated_chat_database(migration_area, monkeypatch):
    from pathlib import Path

    directory, private_connection, schema = migration_area
    packaged = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))

    @contextmanager
    def connection():
        with private_connection() as c:
            c.execute(sql.SQL("SET search_path TO {},public").format(sql.Identifier(schema)))
            yield c

    monkeypatch.setattr(cli, "connection", connection)
    for path in packaged:
        if path.name < "012_buyer_user_memory.sql":
            (directory / path.name).write_text(path.read_text())
    cli.migrate()
    cid, tid = uuid4(), uuid4()
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('buyer','123',1)")
        c.execute("INSERT INTO identities VALUES('person','buyer','approver',true,'test','{}')")
        c.execute(
            "INSERT INTO conversations(id,buyer_id,title,create_key,create_hash) VALUES(%s,'buyer','t','key','h')",
            (cid,),
        )
        c.execute(
            "INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,attempt,requested_by) "
            "VALUES(%s,%s,'turn-key','h','complete',now(),%s,'person')",
            (tid, cid, uuid4()),
        )
        message = c.execute(
            "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'user','Remember 200') RETURNING id",
            (cid, tid),
        ).fetchone()[0]
    for path in packaged:
        (directory / path.name).write_text(path.read_text())
    cli.migrate()
    cli.migrate()
    with connection() as c:
        assert c.execute("SELECT text FROM conversation_messages").fetchone() == ("Remember 200",)
        c.execute(
            "INSERT INTO memories(id,buyer_id,scope,kind,key,value,created_by,updated_by,"
            "source_conversation_id,source_message_id) VALUES(%s,'buyer','buyer','default',"
            "'default.portions','{\"portions\":200}','person','person',%s,%s)",
            (uuid4(), cid, message),
        )
        assert c.execute(
            "SELECT count(*) FROM memories WHERE search @@ to_tsquery('simple','portions')"
        ).fetchone() == (1,)
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(packaged)
