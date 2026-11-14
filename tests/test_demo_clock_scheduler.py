"""JNP3-CLK-003/004/008: the demo clock and the scheduler (owner answers Q-113, Q-114, 2026-11-14).

THESE TESTS ARE THE SPEC (written before the code, branch p3/flow-tests; see the contract at the
top of tests/test_demo_clock.py). After a buyer's demo jump the scheduler treats every date the
jump skipped as if time had passed with the scheduler running: each date runs in date order, on its
own date, with no RUN_MISSED, no late shift and no skip. When `now` is passed in (every existing
scheduler test) the scheduler behaves exactly as before. All orders are mocks; fixture supplier.

How the scheduler learns the time: `scheduler.run_due_schedules(service)` with no `now` asks
`clock.app_now(buyer_id)` for each authorization's buyer (and `clock.real_now()` otherwise), then
processes each authorization's due dates at their own run time. `scheduler.materialise` and
`open_dates` follow the same rule.
"""

from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import psycopg
import pytest
from test_scheduler_engine import TODAY, at, many, one, scheduled
from wsc_support import add_second_buyer

from aimo import auth, conversations, scheduler
from aimo.config import settings
from aimo.db import connection
from aimo.schemas import CommitRequest, PrepareRequest

pytestmark = pytest.mark.usefixtures("demo_mode")  # these tests start schedules today

BUYER, ACTOR = "demo-hotel", "buyer"


def _days(n):
    return timedelta(days=n)


def key():
    return str(uuid4())


@pytest.fixture
def clock():
    return import_module("aimo.clock")


def wipe_clock_tables():
    try:
        with connection() as c:
            c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
            c.execute("TRUNCATE demo_clock, demo_clock_events")
    except psycopg.errors.UndefinedTable:
        pass  # the migration is not written yet; the tests fail on their own


@pytest.fixture(autouse=True)
def clean_clock_tables():
    wipe_clock_tables()
    yield
    wipe_clock_tables()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings(), "demo_clock_enabled", True)


@pytest.fixture
def pinned(clock, monkeypatch):
    """Real time fixed at 08:00 Helsinki today (after the 06:00 run hour)."""
    instant = at(TODAY, 8, 0)
    monkeypatch.setattr(clock, "real_now", lambda: instant)
    return instant


def drive(service, limit=80, **kw):
    """Run passes (no `now`: the scheduler reads the clock itself) until nothing is left to do."""
    passes = 0
    while passes < limit and scheduler.run_due_schedules(service, **kw):
        passes += 1
    assert passes < limit, "the scheduler never settled"
    return passes


def runs_of(schedule):
    return many(
        "SELECT * FROM scheduled_runs WHERE authorization_id=%s ORDER BY scheduled_date",
        schedule["id"],
    )


def offset_days_of(schedule):
    row = one(
        "SELECT delivery_offset_days FROM scheduled_authorizations WHERE id=%s", schedule["id"]
    )
    return row["delivery_offset_days"]


def test_after_a_jump_every_skipped_date_runs_in_order(
    clock, enabled, pinned, buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order)  # daily, first run today
    clock.advance(BUYER, ACTOR, days=3, idempotency_key=key())
    drive(service)
    runs = runs_of(s)
    assert [r["scheduled_date"] for r in runs] == [TODAY + _days(i) for i in range(4)]
    assert [r["status"] for r in runs] == ["committed"] * 4
    assert all(r["reason_code"] is None for r in runs)  # no RUN_MISSED, no PAUSED skip
    assert not any(r["reason"] for r in runs)  # and no RAN_LATE
    offset = offset_days_of(s)
    assert [r["delivery_date"] for r in runs] == [r["scheduled_date"] + _days(offset) for r in runs]
    placed = many(
        "SELECT r.scheduled_date FROM scheduled_runs r JOIN orders o ON o.id=r.order_id "
        "WHERE r.authorization_id=%s ORDER BY o.created_at, r.scheduled_date",
        s["id"],
    )
    assert [r["scheduled_date"] for r in placed] == [r["scheduled_date"] for r in runs]
    assert one("SELECT count(*) AS n FROM orders")["n"] == 1 + 4  # the source order plus four runs
    assert (
        one("SELECT status FROM scheduled_authorizations WHERE id=%s", s["id"])["status"]
        == "active"
    )


def test_without_a_jump_only_todays_run_happens(
    clock, enabled, pinned, buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order)
    drive(service)
    assert [r["scheduled_date"] for r in runs_of(s)] == [TODAY]


def test_a_disabled_clock_ignores_an_offset_row(clock, pinned, buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    with connection() as c:
        c.execute(
            "INSERT INTO demo_clock(buyer_id,offset_seconds,updated_at) VALUES(%s,%s,now())",
            (BUYER, 3 * 86400),
        )
    assert settings().demo_clock_enabled is False
    drive(service)
    assert [r["scheduled_date"] for r in runs_of(s)] == [TODAY]


def test_a_passed_in_now_still_wins_over_the_clock(
    clock, enabled, pinned, buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order)
    clock.advance(BUYER, ACTOR, days=3, idempotency_key=key())
    while scheduler.run_due_schedules(service, now=at(TODAY, 7)):
        pass
    assert [r["scheduled_date"] for r in runs_of(s)] == [TODAY]  # as every existing test expects


def test_the_scheduler_follows_each_buyers_own_clock(
    clock, enabled, pinned, buyer, service, placed_order, request_data
):
    mine = scheduled(buyer, service, placed_order)
    other = add_second_buyer()["approver"]
    with connection() as c:  # add_second_buyer makes no scheduler identity; a run needs one
        c.execute(
            """INSERT INTO identities(id,buyer_id,role,active,credential_hash,authority)
            VALUES('scheduler:other','other','scheduler',true,'!scheduler-no-login','{}'::jsonb)"""
        )
        c.execute("INSERT INTO scheduler_identities VALUES('other','scheduler:other')")
    data = dict(request_data, idempotency_key=key())
    p = service.prepare_order(auth.internal_agent(other), PrepareRequest.model_validate(data))
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=key())
    receipt = conversations.confirm(other, p["proposal_id"], body, service)
    theirs = scheduled(other, service, {"order_id": receipt["order_id"]})
    clock.advance(BUYER, ACTOR, days=3, idempotency_key=key())  # only the first buyer jumps
    drive(service)
    assert [r["scheduled_date"] for r in runs_of(mine)] == [TODAY + _days(i) for i in range(4)]
    assert [r["scheduled_date"] for r in runs_of(theirs)] == [TODAY]
    assert all(r["status"] == "committed" for r in runs_of(mine) + runs_of(theirs))
