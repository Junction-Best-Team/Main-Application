"""Owner answers Q-103 and Q-104 on the standing orders (Draft CNF-038 and CNF-039).

Q-103: the first run date is tomorrow or later and at most 365 days ahead; a demo switch
(SCHEDULER_DEMO_MODE, off by default) allows today and a "run now" trigger that goes through every
normal check. Q-104: a date missed by a short outage runs late, within a grace window, without a
disruption. Fixture supplier data; every order is a mock.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_http import login
from test_scheduler_engine import (
    TODAY,
    at,
    drive,
    many,
    one,
    orders,
    run_of,
    schedule_row,
    scheduled,
)
from test_schedules import create_body, make, preview_body, refused

from aimo import auth, conversations, scheduler, schedules
from aimo.api import create_app
from aimo.config import settings
from aimo.schemas import CommitRequest, PrepareRequest


@pytest.fixture
def demo_off(monkeypatch):
    monkeypatch.setattr(settings(), "scheduler_demo_mode", False)


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


def preview_on(buyer, service, order, day):
    return schedules.preview(buyer, preview_body(order, first_run_date=str(day)), service)


# --- Q-103: the first run date ----------------------------------------------------------------


def test_the_first_run_date_is_tomorrow_or_later_and_at_most_a_year_ahead(
    buyer, service, placed_order, demo_off
):
    today = scheduler.helsinki_today()
    for bad in (today - timedelta(days=1), today, today + timedelta(days=366)):
        err = refused(
            "INVALID_FIRST_RUN_DATE",
            schedules.preview,
            buyer,
            preview_body(placed_order, first_run_date=str(bad)),
            service,
        )
        assert err.status == 422
    for good in (today + timedelta(days=1), today + timedelta(days=365)):
        assert preview_on(buyer, service, placed_order, good)["first_run_date"] == good


def test_a_year_ahead_schedule_still_ends_a_year_after_its_first_run(
    buyer, service, placed_order, demo_off
):
    far = scheduler.helsinki_today() + timedelta(days=365)
    made = schedules.create(
        buyer,
        create_body(
            placed_order,
            preview_on(buyer, service, placed_order, far),
            first_run_date=str(far),
        ),
        service,
    )
    assert made["valid_until"] == far + timedelta(days=365)


def test_demo_mode_allows_today_but_not_the_past(buyer, service, placed_order, demo_mode):
    today = scheduler.helsinki_today()
    assert preview_on(buyer, service, placed_order, today)["first_run_date"] == today
    refused(
        "INVALID_FIRST_RUN_DATE",
        schedules.preview,
        buyer,
        preview_body(placed_order, first_run_date=str(today - timedelta(days=1))),
        service,
    )


def test_a_replace_defaults_to_tomorrow_at_the_earliest(buyer, service, placed_order, demo_off):
    from aimo.schedule_schemas import ScheduleEditPreviewRequest

    old = make(buyer, service, placed_order)
    with schedules.connection() as c:
        c.execute(
            "UPDATE scheduled_authorizations SET status='stopped',stop_reason='RUN_MISSED',next_run_date=NULL"
        )
    edit = schedules.preview_edit(buyer, old["id"], ScheduleEditPreviewRequest(), service)
    assert edit["first_run_date"] >= scheduler.helsinki_today() + timedelta(days=1)


# --- CNF-038: the demo trigger ----------------------------------------------------------------


def test_run_now_is_off_by_default_and_creates_nothing(buyer, service, placed_order, demo_off):
    s = make(buyer, service, placed_order)
    err = refused("SCHEDULE_DEMO_DISABLED", schedules.run_now, buyer, s["id"], service)
    assert err.status == 403
    assert one("SELECT count(*) AS n FROM scheduled_runs")["n"] == 0


def test_run_now_makes_todays_run_due_before_the_run_hour_and_the_worker_places_it(
    buyer, service, placed_order, demo_mode
):
    s = make(buyer, service, placed_order)  # first run is in a few days
    before = len(orders())
    early = at(hour=5, minute=0)  # before 06:00: a normal run would not start
    assert drive(service, early) == 0
    result = schedules.run_now(buyer, s["id"], service)
    assert (
        result["last_run"]["status"] == "due"
        and result["last_run"]["scheduled_date"] == scheduler.helsinki_today()
    )
    assert drive(service, early) == 2  # prepare, commit: the normal engine, no inline shortcut
    run = run_of(s)
    assert run["status"] == "committed" and len(orders()) == before + 1
    receipt = one("SELECT receipt FROM orders WHERE id=%s", run["order_id"])["receipt"]
    assert receipt["label"] == "Accepted by demo order service"
    assert receipt["upstream_order_placed"] is False
    actor = one(
        "SELECT actor_id FROM audit_events WHERE proposal_id=%s AND event='accepted_mock'",
        run["proposal_id"],
    )["actor_id"]
    assert actor.startswith("scheduler:")  # the scheduler identity, through its commit gate
    assert schedule_row(s)["status"] == "active"  # and the normal schedule goes on


def test_a_demo_run_is_a_normal_run_with_a_demo_flag_in_its_events(
    buyer, service, placed_order, demo_mode
):
    s = make(buyer, service, placed_order)
    schedules.run_now(buyer, s["id"], service)
    drive(service, at())
    events = many("SELECT event,detail FROM scheduled_run_events ORDER BY id")
    assert [e["event"] for e in events] == ["created", "demo_run_now", "prepared", "committed"]
    assert events[0]["detail"]["demo"] is True and events[1]["detail"]["demo"] is True
    assert run_of(s)["status"] == "committed"  # an ordinary status, no special demo state


def test_run_now_twice_the_same_day_is_one_run_and_one_order(
    buyer, service, placed_order, demo_mode
):
    s = make(buyer, service, placed_order)
    before = len(orders())
    first = schedules.run_now(buyer, s["id"], service)
    again = schedules.run_now(buyer, s["id"], service)
    drive(service, at())
    schedules.run_now(buyer, s["id"], service)  # after it ran
    assert first["last_run"]["id"] == again["last_run"]["id"]
    assert one("SELECT count(*) AS n FROM scheduled_runs")["n"] == 1
    assert len(orders()) == before + 1


def test_run_now_never_skips_a_check(buyer, service, connector, placed_order, demo_mode):
    s = make(buyer, service, placed_order)
    connector.price_multiplier = Decimal("1.5")  # no range was agreed
    schedules.run_now(buyer, s["id"], service)
    before = len(orders())
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "disrupted" and run["reason_code"] == "PRICE_OUTSIDE_RANGE"
    assert schedule_row(s)["status"] == "stopped" and len(orders()) == before


def test_run_now_needs_the_customer_an_active_schedule_and_the_buyers_own(
    buyer, service, placed_order, demo_mode
):
    from test_schedules import other_buyer

    s = make(buyer, service, placed_order)
    refused("FORBIDDEN", schedules.run_now, auth.internal_agent(buyer), s["id"], service)
    refused("NOT_FOUND", schedules.run_now, other_buyer(), s["id"], service)
    schedules.pause(buyer, s["id"])
    refused("SCHEDULE_NOT_ACTIVE", schedules.run_now, buyer, s["id"], service)
    schedules.cancel(buyer, s["id"])
    refused("SCHEDULE_NOT_ACTIVE", schedules.run_now, buyer, s["id"], service)
    assert one("SELECT count(*) AS n FROM scheduled_runs")["n"] == 0


def test_run_now_over_http_needs_a_session_csrf_and_the_flag(http, placed_order, demo_mode):
    headers = login(http)
    base = {"order_id": placed_order["order_id"], "recurrence": {"kind": "days", "interval": 1}}
    first = str(scheduler.helsinki_today() + timedelta(days=3))
    terms = http.post(
        "/api/schedules/preview", headers=headers, json=base | {"first_run_date": first}
    ).json()
    made = http.post(
        "/api/schedules",
        headers=headers,
        json=base
        | {
            "first_run_date": first,
            "price_ceiling_gross": "100.00",
            "agreed_terms_fingerprint": terms["terms_fingerprint"],
            "idempotency_key": str(uuid4()),
        },
    ).json()
    url = f"/api/schedules/{made['id']}/run-now"
    assert http.post(url, json={}).status_code == 403  # cookie only: no token, no origin
    assert http.post(url, json={}, headers=headers | {"X-CSRF-Token": "x"}).status_code == 403
    ok = http.post(url, json={}, headers=headers)
    assert ok.status_code == 200 and ok.json()["last_run"]["status"] == "due"


def test_the_session_reports_whether_the_demo_switch_is_on(http, demo_mode, monkeypatch):
    headers = login(http)
    assert http.get("/api/session").json()["scheduler_demo_mode"] is True
    monkeypatch.setattr(settings(), "scheduler_demo_mode", False)
    assert http.get("/api/session").json()["scheduler_demo_mode"] is False
    assert (
        http.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"username": "buyer", "password": __import__("os").environ["DEMO_BUYER_PASSWORD"]},
        ).json()["scheduler_demo_mode"]
        is False
    )
    assert headers


# --- CNF-039: a short outage runs the date late ----------------------------------------------
# Literal reading (b5): a date runs while now is at most SCHEDULER_GRACE_HOURS (6) after its run
# time (06:00 Helsinki), so until 12:00 the same day; after that it is a RUN_MISSED disruption.


def test_a_run_started_on_time_is_not_flagged_late(buyer, service, placed_order, demo_mode):
    s = scheduled(buyer, service, placed_order)
    drive(service, at(hour=6, minute=5))
    run = run_of(s)
    assert run["status"] == "committed" and not (run["reason"] or {}).get("codes")
    created = one("SELECT detail FROM scheduled_run_events WHERE event='created'")["detail"]
    assert "late" not in created


def test_a_date_missed_by_a_short_outage_runs_late_without_a_disruption(
    buyer, service, placed_order, demo_mode
):
    s = scheduled(buyer, service, placed_order)  # due 06:00; the worker is back at 09:00
    before = len(orders())
    drive(service, at(hour=9))
    run = run_of(s)
    assert run["scheduled_date"] == TODAY and run["status"] == "committed"
    assert run["reason"]["codes"] == ["RAN_LATE"] and len(orders()) == before + 1
    assert schedule_row(s)["status"] == "active"
    created = one("SELECT detail FROM scheduled_run_events WHERE event='created'")["detail"]
    assert created["late"] is True
    note = one("SELECT receipt FROM orders WHERE id=%s", run["order_id"])["receipt"][
        "scheduled_run"
    ]
    assert note["ran_late"] is True and note["scheduled_date"] == str(TODAY)
    assert note["delivery_date"] == str(TODAY + timedelta(days=2))  # still tomorrow or later


def test_the_window_ends_six_hours_after_the_run_time(buyer, service, placed_order, demo_mode):
    inside = scheduled(buyer, service, placed_order)
    drive(service, at(hour=12, minute=0))  # exactly 6 hours: still inside
    assert run_of(inside)["status"] == "committed"


def test_beyond_the_grace_window_a_missed_date_is_a_disruption(
    buyer, service, placed_order, demo_mode
):
    s = scheduled(buyer, service, placed_order)
    drive(service, at(hour=12, minute=1))
    run = run_of(s)
    assert run["status"] == "disrupted" and run["reason_code"] == "RUN_MISSED"
    assert schedule_row(s)["status"] == "stopped"


def test_a_date_from_a_past_day_is_missed_with_the_default_window(
    buyer, service, placed_order, demo_mode
):
    s = scheduled(buyer, service, placed_order)
    drive(service, at(TODAY + timedelta(days=1), hour=2))  # 20 hours after the run time
    assert run_of(s)["reason_code"] == "RUN_MISSED"


def test_the_grace_window_is_a_setting(buyer, service, placed_order, demo_mode, monkeypatch):
    monkeypatch.setattr(settings(), "scheduler_grace_hours", 0)
    s = scheduled(buyer, service, placed_order)
    drive(service, at(hour=7))
    assert run_of(s)["reason_code"] == "RUN_MISSED"


def test_thirty_hours_reproduces_the_end_of_the_date_reading(
    buyer, service, placed_order, demo_mode, monkeypatch
):
    monkeypatch.setattr(settings(), "scheduler_grace_hours", 30)
    s = scheduled(buyer, service, placed_order)
    drive(service, at(TODAY + timedelta(days=1), hour=2))
    assert run_of(s)["status"] == "committed" and run_of(s)["reason"]["codes"] == ["RAN_LATE"]


def test_a_late_run_moves_a_delivery_date_that_has_passed_to_tomorrow(
    buyer, service, request_data, demo_mode, monkeypatch
):
    monkeypatch.setattr(settings(), "scheduler_grace_hours", 30)
    request_data["delivery_date"] = str(TODAY + timedelta(days=1))  # a one-day lead order
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    receipt = conversations.confirm(
        buyer,
        p["proposal_id"],
        CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4())),
        service,
    )
    s = scheduled(buyer, service, {"order_id": receipt["order_id"]})
    drive(service, at(TODAY + timedelta(days=1), hour=2))  # the scheduled delivery date is today
    run = run_of(s)
    assert run["status"] == "committed" and run["delivery_date"] == TODAY + timedelta(days=2)
    assert (
        one("SELECT receipt FROM orders WHERE id=%s", run["order_id"])["receipt"]["scheduled_run"][
            "ran_late"
        ]
        is True
    )


def test_a_late_date_that_cannot_be_prepared_is_a_normal_disruption(
    buyer, service, connector, placed_order, demo_mode
):
    s = scheduled(buyer, service, placed_order)
    connector.stock = {"464306": "0"}
    drive(service, at(hour=9))
    assert run_of(s)["reason_code"] == "PRODUCT_UNAVAILABLE"
