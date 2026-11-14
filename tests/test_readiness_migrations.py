"""/health/ready fails (503) when the migration ledger lacks a migration the code ships.

A correctly migrated database (every packaged migration in schema_migrations) stays ready; extra
ledger rows, an unreadable ledger or a missing packaged folder never make it fail. The failure
body names nothing internal. The ledger rows are removed and restored inside each test; the test
database is a scratch database (name ends in _test). Fixture mode.
"""

from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from aimo import api, schema_state
from aimo.db import connection
from aimo.service import Service

PACKAGED = sorted(
    p.name for p in (Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")
)


def ready():
    with TestClient(api.create_app(Service())) as http:
        return http.get("/health/ready")


@contextmanager
def ledger_without(*versions):
    with connection() as c:
        saved = c.execute(
            "SELECT version, applied_at FROM schema_migrations WHERE version = ANY(%s)",
            (list(versions),),
        ).fetchall()
        assert len(saved) == len(versions), "the test database should have every migration"
        c.execute("DELETE FROM schema_migrations WHERE version = ANY(%s)", (list(versions),))
    try:
        yield
    finally:
        with connection() as c:
            for row in saved:
                c.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (%s, %s)",
                    (row["version"], row["applied_at"]),
                )


def test_a_fully_migrated_database_is_ready():
    assert len(PACKAGED) >= 15  # 001 to 011 plus the two 012 files and 013
    response = ready()
    assert response.status_code == 200 and response.json()["status"] == "ready"
    assert schema_state.missing_migrations() == []


@pytest.mark.parametrize(
    "missing",
    [
        ["010_meal_authorization_withdrawals.sql"],
        ["009_product_withdrawn_since.sql", "013_catalog_sync_withdrawals.sql"],
        ["011_proposal_revision_ordering.sql"],
    ],
)
def test_a_missing_ledger_row_makes_it_not_ready_without_naming_anything(missing):
    with ledger_without(*missing):
        assert schema_state.missing_migrations() == sorted(missing)
        response = ready()
    assert response.status_code == 503
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "SCHEMA_NOT_READY"
    for name in missing:  # no file name, number or table name leaks
        assert name not in response.text and name.split("_")[0] not in response.text
    assert ready().status_code == 200  # restored


def test_extra_or_renamed_ledger_rows_do_not_fail_it():
    with connection() as c:
        c.execute(
            "INSERT INTO schema_migrations(version) VALUES ('008_proposal_revision_ordering.sql')"
        )
    try:
        assert ready().status_code == 200
    finally:
        with connection() as c:
            c.execute(
                "DELETE FROM schema_migrations WHERE version='008_proposal_revision_ordering.sql'"
            )


def test_an_unreadable_ledger_is_not_a_failure(monkeypatch):
    def denied():
        raise psycopg.errors.InsufficientPrivilege("permission denied for table schema_migrations")

    monkeypatch.setattr(schema_state, "applied_versions", denied)
    assert schema_state.missing_migrations() == []
    assert ready().status_code == 200


def test_a_missing_packaged_folder_skips_the_check(monkeypatch, tmp_path):
    monkeypatch.setattr(schema_state, "MIGRATIONS_DIR", tmp_path / "absent")
    with ledger_without("010_meal_authorization_withdrawals.sql"):
        assert ready().status_code == 200
