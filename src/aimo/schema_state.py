"""Which of the packaged migrations the database ledger is missing.

The release applies migrations in a Job before the new images start; nothing in the app
migrates. This lets /health/ready notice a database that lacks a migration the code ships (for
example 010 for meal authorization withdrawals), instead of answering ready and then failing with
HTTP 500 on the first purchase. It never raises: if the ledger cannot be read or the migrations
folder is not packaged, it cannot tell and reports nothing missing, so it can never take down a
deployment that is otherwise healthy.
"""

import logging
from pathlib import Path

import psycopg

from aimo.db import connection

log = logging.getLogger(__name__)

# Same folder the migration runner reads (aimo.cli.ROOT / "migrations").
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def applied_versions() -> set[str]:
    with connection() as c:
        return {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}


def missing_migrations() -> list[str]:
    """Packaged migration files with no ledger row, sorted; empty when unknown."""
    try:
        packaged = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    except OSError:
        return []
    if not packaged:
        return []
    try:
        applied = applied_versions()
    except (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable):
        log.warning("Cannot read the migration ledger; not reporting missing migrations.")
        return []
    return [name for name in packaged if name not in applied]
