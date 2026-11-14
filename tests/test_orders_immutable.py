"""Orders are history: a saved receipt can never be rewritten or removed (JNP3-CNF-017).

The demo order service's acceptance is a mock; these tests use the authored fixture catalog and
invented FixtureClient prices. Migration 008_orders_immutable.sql adds the trigger.
"""

from pathlib import Path

import psycopg
import pytest

from aimo import auth, conversations
from aimo.db import connection
from aimo.schemas import CommitRequest, PrepareRequest

MIGRATION = Path(__file__).parents[1] / "migrations" / "008_orders_immutable.sql"


def order_of(service, buyer, request_data):
    """Commit one mock order the way the browser does and return (receipt, order id)."""
    actor = auth.internal_agent(buyer)
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key="order-key-1")
    receipt = conversations.confirm(buyer, p["proposal_id"], body, service)
    return actor, p, body, receipt


def test_an_order_row_cannot_be_updated_or_deleted(service, buyer, request_data):
    _, _, _, receipt = order_of(service, buyer, request_data)
    for statement in (
        "UPDATE orders SET receipt='{}'::jsonb",
        "UPDATE orders SET revision=revision+1",
        "UPDATE orders SET buyer_id=buyer_id",
        "DELETE FROM orders",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
            with connection() as c:
                c.execute(statement)
    with connection() as c:
        (row,) = c.execute("SELECT receipt FROM orders").fetchall()
    assert row["receipt"] == receipt


def test_commit_and_saved_receipt_replay_still_work(service, connector, buyer, request_data):
    actor, p, body, receipt = order_of(service, buyer, request_data)
    assert receipt["status"] == "accepted_mock" and receipt["label"].startswith("Accepted by demo")
    connector.lookup = lambda *args: (_ for _ in ()).throw(AssertionError("no supplier on replay"))
    assert conversations.confirm(buyer, p["proposal_id"], body, service) == receipt
    assert service.get_order(actor, receipt["order_id"]) == receipt
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 1
        # The proposal still points at its order: only the orders table is frozen.
        (proposal,) = c.execute("SELECT order_id FROM proposals").fetchall()
    assert str(proposal["order_id"]) == receipt["order_id"]


def test_orders_use_the_same_guard_as_the_other_history_tables():
    with connection() as c:
        rows = c.execute(
            """SELECT c.relname AS table_name, p.proname AS function_name
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_proc p ON p.oid=t.tgfoid
            WHERE NOT t.tgisinternal AND p.proname='immutable_record'"""
        ).fetchall()
    assert "orders" in {r["table_name"] for r in rows}
    assert {"proposal_revisions", "audit_events", "customer_confirmations"} <= {
        r["table_name"] for r in rows
    }


def test_migration_is_safe_on_a_populated_database_and_can_be_reapplied(
    service, buyer, request_data
):
    """The trigger changes no rows; applying the file again to a database that already holds
    orders (with or without the trigger) leaves them untouched and the guard in place."""
    _, _, _, receipt = order_of(service, buyer, request_data)
    with connection() as c:
        c.execute("DROP TRIGGER IF EXISTS immutable_orders ON orders")
        before = c.execute("SELECT id, receipt, created_at FROM orders").fetchall()
    for _ in range(2):  # first from "no trigger", then re-applied over an existing one
        with connection() as c:
            c.execute(MIGRATION.read_text())
    with connection() as c:
        assert c.execute("SELECT id, receipt, created_at FROM orders").fetchall() == before
    with pytest.raises(psycopg.errors.RaiseException):
        with connection() as c:
            c.execute("DELETE FROM orders")
    assert before[0]["receipt"] == receipt
