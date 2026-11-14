"""Which database objects the code needs from migrations 008 onward are missing.

The release applies migrations in a Job before the new images start; nothing in the app
migrates. /health/ready uses this to notice a database that lacks an object the code ships (for
example the table of migration 010), instead of answering ready and then failing with HTTP 500
on the first purchase.

It probes the objects themselves through pg_catalog and to_regclass, which every role can read.
It deliberately does NOT read schema_migrations: configure_runtime_role revokes all access to that
table from the runtime role, so as the deployed API a ledger read is denied.

It never raises. If a probe errors or a catalog read is denied it cannot tell, so it reports
nothing missing; it can therefore never take down a deployment that is otherwise healthy.
"""

import logging

from psycopg.rows import tuple_row

from aimo.db import connection

log = logging.getLogger(__name__)

# Migration file name -> the objects the code needs from it: (kind, name...) with kind one of
# table, view, index (a relation name), column (table, column), trigger (table, trigger),
# or function (full signature).
# A new migration must add its entry (tests/test_readiness_migrations.py fails until it does).
MANIFEST: dict[str, list[tuple[str, ...]]] = {
    "008_orders_immutable.sql": [("trigger", "orders", "immutable_orders")],
    "009_product_withdrawn_since.sql": [("column", "products", "withdrawn_since")],
    "010_meal_authorization_withdrawals.sql": [("table", "meal_authorization_withdrawals")],
    "011_proposal_revision_ordering.sql": [
        ("column", "proposals", "updated_at"),
        ("index", "proposals_buyer_updated"),
    ],
    "012_buyer_user_memory.sql": [
        ("table", "memories"),
        ("table", "memory_mutations"),
        ("column", "conversation_turns", "submitted_by"),
    ],
    "012_catalog_import_profile.sql": [("column", "catalog_generations", "import_profile")],
    "013_catalog_sync_withdrawals.sql": [
        ("column", "catalog_generations", "source_product_count"),
        ("view", "catalog_protected_products"),
    ],
    "014_policy_settings.sql": [
        ("table", "policy_managers"),
        ("table", "policy_changes"),
        ("trigger", "policy_changes", "immutable_policy_changes"),
        ("function", "save_buyer_policy(text,integer,jsonb)"),
    ],
    "018_purge_unfinished_proposals.sql": [
        ("table", "purged_proposals"),
        ("trigger", "purged_proposals", "immutable_purged_proposals"),
        ("trigger", "audit_events", "immutable_audit"),
    ],
    "019_history_immutability.sql": [
        ("trigger", "recipe_plan_revisions", "immutable_recipe_plan_revisions"),
        ("trigger", "recipe_versions", "immutable_recipe_versions"),
        ("trigger", "orders", "immutable_truncate"),
    ],
}

_RELATION = "SELECT to_regclass(%s) IS NOT NULL"
_FUNCTION = "SELECT to_regprocedure(%s) IS NOT NULL"
_COLUMN = (
    "SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(%s) "
    "AND attname = %s AND attnum > 0 AND NOT attisdropped)"
)
_TRIGGER = (
    "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = to_regclass(%s) "
    "AND tgname = %s AND NOT tgisinternal)"
)


def _present(cursor, check: tuple[str, ...]) -> bool:
    kind, *names = check
    query = {"table": _RELATION, "view": _RELATION, "index": _RELATION}.get(kind)
    if query is None:
        query = {"column": _COLUMN, "trigger": _TRIGGER, "function": _FUNCTION}[kind]
    return bool(cursor.execute(query, names).fetchone()[0])


def missing_in(conn) -> list[str]:
    """Migration file names, sorted, with at least one needed object missing, on this connection."""
    with conn.cursor(row_factory=tuple_row) as cursor:
        return sorted(
            name
            for name, checks in MANIFEST.items()
            if not all(_present(cursor, check) for check in checks)
        )


def missing_migrations() -> list[str]:
    """Same, on a pooled connection; empty when it cannot tell (never raises)."""
    try:
        with connection() as c:
            return missing_in(c)
    except Exception as error:  # a healthy deployment must never be taken down by this probe
        log.warning("Cannot probe the database schema; not reporting missing migrations: %s", error)
        return []
