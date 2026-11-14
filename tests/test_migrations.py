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
