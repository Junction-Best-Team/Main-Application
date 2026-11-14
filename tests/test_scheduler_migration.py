"""JNP3-CNF-020/023/025/026/035/037: the scheduler tables, their guards and the scheduler identity.

Guards that are the rules of the data: authorized terms never change, only active <-> paused
may repeat, a run is unique per authorization and date, history tables are append-only, and a
placed order can never be cancelled. A person is not needed: the scheduler identity has no login.
"""

from datetime import date, timedelta
from uuid import uuid4

import psycopg
import pytest

from aimo import auth, conversations
from aimo.db import Problem, connection, js
from aimo.schemas import CommitRequest, PrepareRequest

TODAY = date(2026, 11, 20)


@pytest.fixture
def order(service, buyer, request_data):
    """A placed (mock) order of the demo buyer: the source of a standing order."""
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    receipt = conversations.confirm(buyer, p["proposal_id"], body, service)
    return {"order_id": receipt["order_id"], "proposal_id": p["proposal_id"]}


def authorization(order, **changes):
    row = {
        "id": uuid4(),
        "buyer_id": "demo-hotel",
        "created_by": "buyer",
        "source_order_id": order["order_id"],
        "create_key": str(uuid4()),
        "create_hash": "h",
        "request": js({}),
        "agreed_lines": js([]),
        "terms_fingerprint": "f",
        "currency": "EUR",
        "agreed_gross_total": "10.00",
        "price_ceiling_gross": "12.00",
        "delivery_offset_days": 1,
        "recurrence": js({"kind": "days", "interval": 7}),
        "first_run_date": TODAY,
        "valid_until": TODAY + timedelta(days=365),
        "next_run_date": TODAY,
    } | changes
    with connection() as c:
        c.execute(
            f"INSERT INTO scheduled_authorizations({','.join(row)}) VALUES({','.join(['%s'] * len(row))})",
            list(row.values()),
        )
    return row["id"]


def update(aid, **changes):
    sets = ",".join(f"{k}=%s" for k in changes)
    with connection() as c:
        c.execute(
            f"UPDATE scheduled_authorizations SET {sets} WHERE id=%s", [*changes.values(), aid]
        )


def status(aid):
    with connection() as c:
        return c.execute(
            "SELECT status FROM scheduled_authorizations WHERE id=%s", (aid,)
        ).fetchone()["status"]


def run(aid, day=TODAY, **changes):
    row = {
        "id": uuid4(),
        "authorization_id": aid,
        "buyer_id": "demo-hotel",
        "scheduled_date": day,
        "delivery_date": day + timedelta(days=1),
    } | changes
    with connection() as c:
        c.execute(
            f"INSERT INTO scheduled_runs({','.join(row)}) VALUES({','.join(['%s'] * len(row))})",
            list(row.values()),
        )
    return row["id"]


# --- the scheduler identity -----------------------------------------------------------------


def test_the_demo_buyer_has_a_scheduler_identity_that_cannot_log_in():
    with connection() as c:
        row = c.execute(
            """SELECT i.* FROM scheduler_identities s JOIN identities i ON i.id=s.identity_id
            WHERE s.buyer_id='demo-hotel'"""
        ).fetchone()
    assert row and row["role"] == "scheduler" and row["active"] and row["authority"] == {}
    with pytest.raises(Problem) as refused:
        auth.login(row["id"], "!scheduler-no-login", "127.0.0.1")
    assert refused.value.code == "LOGIN_FAILED"


def test_a_scheduler_is_not_the_buyers_internal_agent():
    with connection() as c:
        agent = c.execute(
            "SELECT identity_id FROM internal_agents WHERE buyer_id='demo-hotel'"
        ).fetchone()
        sched = c.execute(
            "SELECT identity_id FROM scheduler_identities WHERE buyer_id='demo-hotel'"
        ).fetchone()
    assert agent["identity_id"] != sched["identity_id"]


def test_only_known_roles_exist():
    with connection() as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute("INSERT INTO identities VALUES('x','demo-hotel','janitor',true,'!','{}')")


# --- authorization guards -------------------------------------------------------------------


def test_authorized_terms_never_change(order):
    aid = authorization(order)
    for column, value in [
        ("price_ceiling_gross", "99.00"),
        ("line_rules", js({"1": {"accepted_substitutes": ["2"]}})),
        ("recurrence", js({"kind": "days", "interval": 1})),
        ("valid_until", TODAY + timedelta(days=10)),
        ("agreed_lines", js([{"x": 1}])),
    ]:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            update(aid, **{column: value})


def test_pause_and_resume_can_repeat_but_a_finished_authorization_is_final(order):
    aid = authorization(order)
    with connection() as c:
        for state in ("paused", "active", "paused"):
            c.execute(
                "UPDATE scheduled_authorizations SET status=%s,paused_at=%s WHERE id=%s",
                (state, "2026-11-21T10:00Z" if state == "paused" else None, aid),
            )
    assert status(aid) == "paused"
    update(aid, status="stopped", stop_reason="RUN_MISSED", paused_at=None)
    for target in ("active", "cancelled"):
        with pytest.raises(psycopg.errors.RaiseException, match="never changes"):
            update(aid, status=target, stop_reason=None)


def test_only_the_movable_columns_change_while_active(order):
    aid = authorization(order)
    update(aid, next_run_date=TODAY + timedelta(days=7), updated_at="2026-11-21T10:00Z")
    with connection() as c, pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        c.execute("DELETE FROM scheduled_authorizations WHERE id=%s", (aid,))


@pytest.mark.parametrize(
    ("changes", "rule"),
    [
        ({"valid_until": TODAY + timedelta(days=366)}, "sched_auth_one_year"),
        ({"price_ceiling_gross": "9.99"}, "sched_auth_ceiling"),
        ({"status": "stopped"}, "sched_auth_stop_reason"),
        ({"status": "paused"}, "sched_auth_paused_at"),
        ({"delivery_offset_days": 0}, "scheduled_authorizations_delivery_offset_days_check"),
        ({"status": "reopened"}, "scheduled_authorizations_status_check"),
    ],
)
def test_the_table_refuses_an_impossible_authorization(order, changes, rule):
    with pytest.raises(psycopg.errors.CheckViolation, match=rule):
        authorization(order, **changes)


def test_one_create_key_per_buyer_and_the_creator_must_belong_to_the_buyer(order):
    authorization(order, create_key="same-key-1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        authorization(order, create_key="same-key-1")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        authorization(order, created_by="not-an-identity")


# --- runs and history -----------------------------------------------------------------------


def test_one_run_per_authorization_and_date(order):
    aid = authorization(order)
    run(aid)
    with pytest.raises(psycopg.errors.UniqueViolation, match="scheduled_runs_once"):
        run(aid)
    run(aid, TODAY + timedelta(days=7))
    run(authorization(order), TODAY)  # another authorization may use the same date


def test_a_disrupted_or_skipped_run_names_its_reason(order):
    aid = authorization(order)
    with pytest.raises(psycopg.errors.CheckViolation, match="scheduled_runs_reason"):
        run(aid, status="disrupted")
    run(aid, status="skipped", reason_code="PAUSED")


def test_a_proposal_or_order_belongs_to_one_run(order):
    first, second = authorization(order), authorization(order)
    run(first, proposal_id=order["proposal_id"])
    with pytest.raises(psycopg.errors.UniqueViolation):
        run(second, proposal_id=order["proposal_id"])


def test_run_and_authorization_events_are_append_only(order):
    aid = authorization(order)
    rid = run(aid)
    with connection() as c:
        c.execute(
            "INSERT INTO scheduled_run_events(run_id,actor_id,event,detail) VALUES(%s,'x','prepared','{}')",
            (rid,),
        )
        c.execute(
            "INSERT INTO scheduled_authorization_events(authorization_id,actor_id,event,detail) "
            "VALUES(%s,'x','created','{}')",
            (aid,),
        )
    for table in ("scheduled_run_events", "scheduled_authorization_events"):
        for statement in (f"UPDATE {table} SET event='x'", f"DELETE FROM {table}"):
            with connection() as c, pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                c.execute(statement)


# --- cancellations --------------------------------------------------------------------------


def test_a_placed_order_cannot_be_cancelled_but_an_open_request_can(
    order, service, buyer, request_data
):
    with connection() as c, pytest.raises(psycopg.errors.RaiseException, match="placed order"):
        c.execute(
            "INSERT INTO order_request_cancellations(proposal_id,buyer_id,reason,cancelled_by) "
            "VALUES(%s,'demo-hotel','customer_revised','buyer')",
            (order["proposal_id"],),
        )
    request_data["idempotency_key"] = str(uuid4())
    open_request = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    with connection() as c:
        c.execute(
            "INSERT INTO order_request_cancellations(proposal_id,buyer_id,reason,cancelled_by) "
            "VALUES(%s,'demo-hotel','run_disrupted','buyer')",
            (open_request["proposal_id"],),
        )
    for statement in (
        "UPDATE order_request_cancellations SET reason='run_retry'",
        "DELETE FROM order_request_cancellations",
    ):
        with connection() as c, pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            c.execute(statement)
    request_data["idempotency_key"] = str(uuid4())
    another = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    with connection() as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute(
            "INSERT INTO order_request_cancellations(proposal_id,buyer_id,reason,cancelled_by) "
            "VALUES(%s,'demo-hotel','whim','buyer')",
            (another["proposal_id"],),
        )


# --- the system-authored message ------------------------------------------------------------


def test_the_conversation_message_roles_include_system(buyer):
    cid = conversations.create(
        buyer,
        __import__("aimo.chat_schemas", fromlist=["x"]).ConversationCreate(
            idempotency_key=str(uuid4())
        ),
    )["id"]
    with connection() as c:
        tid = uuid4()
        c.execute(
            "INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,attempt)"
            " VALUES(%s,%s,'k','h','complete',now(),%s)",
            (tid, cid, uuid4()),
        )
        c.execute(
            "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'system','x')",
            (cid, tid),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'tool','x')",
                (cid, tid),
            )


# --- TRUNCATE of the scheduler history -------------------------------------------------------

HISTORY_TABLES = (
    "scheduled_authorizations",
    "scheduled_runs",
    "scheduled_run_events",
    "scheduled_authorization_events",
    "order_request_cancellations",
)


@pytest.mark.parametrize("table", HISTORY_TABLES)
def test_the_scheduler_history_refuses_truncate_unless_the_reset_is_deliberate(table):
    from aimo.config import settings

    with psycopg.connect(settings().database_url) as raw:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
            raw.execute(f"TRUNCATE {table} CASCADE")
        raw.rollback()
        raw.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        raw.execute(f"TRUNCATE {table} CASCADE")  # a deliberate reset, rolled back below
        raw.rollback()
