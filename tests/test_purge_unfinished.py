"""CNF-021: remove proposals and approvals that never became orders after a configured period.

Default 30 days counted from the expiry of the proposal's current revision (owner Q-56); an
append-only purged_proposals record per removal (Q-57); a DELETE of history is allowed only under
the transaction-local flag aimo.purge_unfinished and only for a proposal with no order. Orders and
everything on an ordered proposal are never touched. Fixture catalog, invented prices, mock orders.
"""

import json
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from aimo import approval_workflow as workflow
from aimo import auth, cli, conversations
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest
from aimo.config import Settings, settings
from aimo.db import connection, now
from aimo.permissions import configure_runtime_role
from aimo.schemas import CommitRequest, PrepareRequest

PERIOD = timedelta(days=30)
LATE = timedelta(days=31)


@pytest.fixture
def actor(buyer):
    return auth.internal_agent(buyer)


def prepare(service, actor, data, amount="10"):
    data = data | {
        "idempotency_key": str(uuid4()),
        "lines": [{"product_id": "464306", "amount": amount, "unit": "L"}],
    }
    return service.prepare_order(actor, PrepareRequest.model_validate(data))


def order(service, buyer, p):
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    return conversations.confirm(buyer, p["proposal_id"], body, service)


def count(table, where="", args=()):
    with connection() as c:
        return c.execute(f"SELECT count(*) AS n FROM {table} {where}", args).fetchone()["n"]


def test_the_period_is_a_setting_with_a_30_day_default():
    assert Settings(_env_file=None).unfinished_proposal_retention_days == 30
    assert settings().unfinished_proposal_retention_days >= 1
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    assert "UNFINISHED_PROPOSAL_RETENTION_DAYS=30" in example


def test_a_dry_run_reports_and_deletes_nothing(service, buyer, actor, request_data):
    p = prepare(service, actor, request_data)
    before = {t: count(t) for t in ("proposals", "proposal_revisions", "audit_events", "approvals")}
    result = workflow.purge_unfinished_proposals(PERIOD, as_of=now() + LATE, dry_run=True)
    assert result["dry_run"] is True and result["proposals"] == 1
    assert {t: count(t) for t in before} == before and count("purged_proposals") == 0
    assert str(p["proposal_id"])


def test_each_removal_leaves_one_immutable_record_and_orders_are_untouched(
    service, buyer, actor, request_data
):
    gone = prepare(service, actor, request_data, "11")
    kept = prepare(service, actor, request_data, "12")
    receipt = order(service, buyer, kept)
    workflow.purge_unfinished_proposals(PERIOD, as_of=now() + LATE)
    with connection() as c:
        (row,) = c.execute("SELECT * FROM purged_proposals").fetchall()
    assert str(row["proposal_id"]) == gone["proposal_id"] and row["buyer_id"] == buyer["buyer_id"]
    assert row["last_revision"] == 1 and row["last_outcome"] == gone["policy_outcome"]
    assert row["period_days"] == 30 and row["last_expires_at"] and row["purged_at"]
    for statement in ("UPDATE purged_proposals SET buyer_id='x'", "DELETE FROM purged_proposals"):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
            with connection() as c:
                c.execute("SET LOCAL aimo.purge_unfinished = 'on'")  # the flag does not help here
                c.execute(statement)
    assert service.get_order(actor, receipt["order_id"]) == receipt


def test_a_proposal_that_got_an_order_is_never_deleted_even_if_listed(
    service, buyer, actor, request_data
):
    ordered = prepare(service, actor, request_data)
    order(service, buyer, ordered)
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (buyer["buyer_id"],))
        result = workflow.purge_batch(c, [ordered["proposal_id"]], PERIOD)
    assert result["proposals"] == 0 and count("proposals") == 1 and count("orders") == 1
    assert count("audit_events", "WHERE proposal_id=%s", (ordered["proposal_id"],)) >= 3


@pytest.mark.parametrize("table", ["proposal_revisions", "audit_events", "customer_confirmations"])
def test_the_triggers_allow_a_history_delete_only_under_the_flag_and_without_an_order(
    service, buyer, actor, request_data, table
):
    unfinished = prepare(service, actor, request_data, "11")
    ordered = prepare(service, actor, request_data, "12")
    order(service, buyer, ordered)
    with connection() as c:  # a confirmation on an unfinished proposal, for that table
        c.execute(
            "INSERT INTO customer_confirmations(proposal_id,revision,fingerprint,actor_id,key,"
            "buyer_id) SELECT proposal_id,revision,fingerprint,%s,%s,buyer_id FROM "
            "proposal_revisions JOIN proposals ON id=proposal_id WHERE proposal_id=%s",
            (buyer["id"], "purge-test-key-1", unfinished["proposal_id"]),
        )
    where = "WHERE proposal_id = %s"
    for pid, flag, allowed in (
        (unfinished["proposal_id"], False, False),
        (ordered["proposal_id"], True, False),
        (unfinished["proposal_id"], True, True),
    ):
        with psycopg.connect(settings().database_url) as conn:
            try:
                if flag:
                    conn.execute("SET LOCAL aimo.purge_unfinished = 'on'")
                if allowed:
                    if table == "proposal_revisions":  # children first, as the purge does
                        conn.execute("DELETE FROM approvals WHERE proposal_id=%s", (pid,))
                        conn.execute(
                            "DELETE FROM customer_confirmations WHERE proposal_id=%s", (pid,)
                        )
                    assert conn.execute(f"DELETE FROM {table} {where}", (pid,)).rowcount >= 1
                else:
                    with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
                        conn.execute(f"DELETE FROM {table} {where}", (pid,))
            finally:
                conn.rollback()
    with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
        with connection() as c:  # UPDATE is rejected whatever the flag
            c.execute("SET LOCAL aimo.purge_unfinished = 'on'")
            c.execute(f"UPDATE {table} SET proposal_id = proposal_id")


def test_a_chat_message_keeps_its_text_after_the_purge(service, buyer, actor, request_data):
    p = prepare(service, actor, request_data)
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    body = MessageRequest(text="please buy this", idempotency_key=str(uuid4()))
    conversations.message(
        buyer, cid, body, service,
        lambda *a: AgentTurn(text="Review this basket.", proposal_id=p["proposal_id"]),
    )  # fmt: skip
    assert count("conversation_messages", "WHERE proposal_id IS NOT NULL") == 1
    workflow.purge_unfinished_proposals(PERIOD, as_of=now() + LATE)
    assert count("conversation_messages", "WHERE proposal_id IS NOT NULL") == 0
    assert count("conversation_messages", "WHERE text = 'Review this basket.'") == 1


def test_the_restricted_runtime_role_can_run_the_purge(service, buyer, actor, request_data):
    prepare(service, actor, request_data)
    with psycopg.connect(settings().database_url, row_factory=dict_row) as conn:
        capable = conn.execute(
            "SELECT (rolsuper OR rolcreaterole) AS ok FROM pg_roles WHERE rolname=current_user"
        ).fetchone()["ok"]
        if not capable:
            pytest.skip("The restricted-role case needs CREATEROLE in the test database")
        role = "purge_runtime_" + uuid4().hex
        try:
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            configure_runtime_role(conn, role)  # the grants the release Job applies
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            result = workflow.purge_unfinished_proposals(PERIOD, as_of=now() + LATE, conn=conn)
            assert result["proposals"] == 1
            assert conn.execute("SELECT count(*) AS n FROM purged_proposals").fetchone()["n"] == 1
        finally:
            conn.rollback()
    assert count("proposals") == 1  # the role's run was rolled back with the transaction


def test_the_cli_command_purges_and_a_dry_run_does_not(
    service, buyer, actor, request_data, monkeypatch, capsys
):
    prepare(service, actor, request_data)
    monkeypatch.setattr(workflow, "now", lambda: now() + LATE)
    monkeypatch.setattr(sys, "argv", ["aimo", "purge-proposals", "--dry-run"])
    cli.main()
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["proposals"] == 1
    assert count("proposals") == 1
    monkeypatch.setattr(sys, "argv", ["aimo", "purge-proposals", "--older-than-days", "30"])
    cli.main()
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["proposals"] == 1
    assert count("proposals") == 0 and count("purged_proposals") == 1


@pytest.mark.parametrize("days", ["0", "-2"])
def test_the_cli_refuses_a_period_below_one_day(
    service, buyer, actor, request_data, monkeypatch, days
):
    """A non-positive period would purge proposals that have not even expired yet."""
    prepare(service, actor, request_data)
    monkeypatch.setattr(sys, "argv", ["aimo", "purge-proposals", "--older-than-days", days])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2 and count("proposals") == 1 and count("purged_proposals") == 0
