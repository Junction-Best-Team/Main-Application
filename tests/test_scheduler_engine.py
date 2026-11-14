"""JNP3-CNF-001..025/030/036/037, POL-012: the scheduler run engine, against fixture supplier data.

One pass of `run_due_schedules` does one step of one run: the first pass of a due run prepares and
compares it, the next commits it. `now` is injected, so no test waits for a clock. Every order is a
mock ("Accepted by demo order service"). No model call happens anywhere on this path.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Thread
from uuid import uuid4

import pytest

from aimo import auth, scheduler, schedules
from aimo.db import Problem, connection
from aimo.schedule_schemas import ScheduleCreateRequest, SchedulePreviewRequest
from aimo.upstream import HELSINKI

TODAY = date.today()
DAILY = {"kind": "days", "interval": 1}

pytestmark = pytest.mark.usefixtures("demo_mode")  # these tests start schedules today


def at(day=TODAY, hour=7, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=HELSINKI)


def widen_scope(*extra):
    """Make more products part of the buyer's approved scope (standing product authority)."""
    ids = ["464306", *extra]
    with connection() as c:
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) SELECT buyer_id,2,"
            "jsonb_set(rules,'{approved_product_ids}',%s::jsonb) "
            "FROM policies WHERE buyer_id='demo-hotel' AND version=1",
            (__import__("json").dumps(ids),),
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")


def scheduled(
    buyer, service, order, *, first=TODAY, rules=None, ceiling="100.00", recurrence=DAILY
):
    base = {
        "order_id": order["order_id"],
        "recurrence": recurrence,
        "first_run_date": str(first),
        "line_rules": rules or {},
    }
    terms = schedules.preview(buyer, SchedulePreviewRequest.model_validate(base), service)
    return schedules.create(
        buyer,
        ScheduleCreateRequest.model_validate(
            base
            | {
                "price_ceiling_gross": ceiling,
                "agreed_terms_fingerprint": terms["terms_fingerprint"],
                "idempotency_key": str(uuid4()),
            }
        ),
        service,
    )


def drive(service, now, limit=12):
    done = 0
    while done < limit and scheduler.run_due_schedules(service, now=now):
        done += 1
    return done


def one(sql, *args):
    with connection() as c:
        return c.execute(sql, args).fetchone()


def many(sql, *args):
    with connection() as c:
        return c.execute(sql, args).fetchall()


def orders():
    return many("SELECT * FROM orders ORDER BY created_at")


def run_of(schedule):
    return one("SELECT * FROM scheduled_runs WHERE authorization_id=%s", schedule["id"])


def schedule_row(schedule):
    return one("SELECT * FROM scheduled_authorizations WHERE id=%s", schedule["id"])


# --- the happy path and idempotence ---------------------------------------------------------


def test_a_due_run_is_prepared_then_committed_by_the_scheduler_identity(
    buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order)
    before = len(orders())
    assert scheduler.run_due_schedules(service, now=at()) is True
    run = run_of(s)
    assert run["status"] == "prepared" and run["proposal_id"] and not run["order_id"]
    assert len(orders()) == before  # prepared is not placed
    assert scheduler.run_due_schedules(service, now=at()) is True
    run = run_of(s)
    assert run["status"] == "committed" and run["order_id"]
    placed = one("SELECT * FROM orders WHERE id=%s", run["order_id"])
    assert placed["receipt"]["label"] == "Accepted by demo order service"
    assert placed["receipt"]["upstream_order_placed"] is False
    note = placed["receipt"]["scheduled_run"]
    assert note["run_id"] == str(run["id"]) and note["schedule_id"] == s["id"]
    assert note["substitutions"] == []
    actor = one(
        "SELECT actor_id FROM audit_events WHERE proposal_id=%s AND event='accepted_mock'",
        run["proposal_id"],
    )["actor_id"]
    assert actor.startswith("scheduler:")
    assert schedule_row(s)["status"] == "active"
    assert schedule_row(s)["next_run_date"] == TODAY + timedelta(days=1)
    events = [e["event"] for e in many("SELECT event FROM scheduled_run_events ORDER BY id")]
    assert events == ["created", "prepared", "committed"]


def test_nothing_happens_before_the_run_hour(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    assert scheduler.run_due_schedules(service, now=at(hour=5, minute=59)) is False
    assert run_of(s) is None
    assert scheduler.run_due_schedules(service, now=at(hour=6)) is True


def test_a_repeated_pass_places_one_order_per_date(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    base = len(orders())
    assert drive(service, at()) == 2
    assert scheduler.run_due_schedules(service, now=at()) is False
    first = run_of(s)
    assert drive(service, at(hour=9)) == 0 and len(orders()) == base + 1
    assert run_of(s)["id"] == first["id"]
    assert drive(service, at(TODAY + timedelta(days=1))) == 2  # the next date is a new run
    assert len(orders()) == base + 2
    assert one("SELECT count(*) AS n FROM scheduled_runs")["n"] == 2


def test_concurrent_passes_place_one_order(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    base = len(orders())
    threads = [Thread(target=drive, args=(service, at())) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(orders()) == base + 1 and run_of(s)["status"] == "committed"
    assert one("SELECT count(*) AS n FROM scheduled_runs")["n"] == 1


# --- prices, the ceiling, availability ------------------------------------------------------


def test_a_price_change_inside_the_range_needs_no_agreement(
    buyer, service, connector, placed_order
):
    rules = {"464306": {"accepted_substitutes": [], "price_range_pct": "5"}}
    s = scheduled(buyer, service, placed_order, rules=rules)
    connector.price_multiplier = Decimal("1.04")
    drive(service, at())
    assert run_of(s)["status"] == "committed" and schedule_row(s)["status"] == "active"


def test_a_price_change_outside_the_range_stops_the_schedule(
    buyer, service, connector, placed_order
):
    rules = {"464306": {"accepted_substitutes": [], "price_range_pct": "5"}}
    s = scheduled(buyer, service, placed_order, rules=rules)
    base = len(orders())
    connector.price_multiplier = Decimal("1.20")
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "disrupted" and run["reason_code"] == "PRICE_OUTSIDE_RANGE"
    line = run["reason"]["lines"][0]
    assert line["status"] == "price_outside_range" and line["agreed_gross"] != line["current_gross"]
    assert len(orders()) == base
    stopped = schedule_row(s)
    assert stopped["status"] == "stopped" and stopped["stop_reason"] == "PRICE_OUTSIDE_RANGE"
    assert stopped["next_run_date"] is None
    cancelled = one(
        "SELECT * FROM order_request_cancellations WHERE proposal_id=%s", run["proposal_id"]
    )
    assert cancelled["reason"] == "run_disrupted" and cancelled["run_id"] == run["id"]
    assert drive(service, at(TODAY + timedelta(days=3))) == 0  # a stopped schedule never runs


def test_no_range_means_any_price_change_is_a_disruption(buyer, service, connector, placed_order):
    s = scheduled(buyer, service, placed_order)  # range 0
    connector.price_multiplier = Decimal("1.01")
    drive(service, at())
    assert run_of(s)["reason_code"] == "PRICE_OUTSIDE_RANGE"


def test_the_ceiling_is_a_hard_limit_even_inside_the_range(buyer, service, connector, placed_order):
    rules = {"464306": {"accepted_substitutes": [], "price_range_pct": "50"}}
    terms = schedules.preview(
        buyer,
        SchedulePreviewRequest.model_validate(
            {
                "order_id": placed_order["order_id"],
                "recurrence": DAILY,
                "first_run_date": str(TODAY),
            }
        ),
        service,
    )
    ceiling = str(Decimal(terms["gross_total"]) * Decimal("1.05"))
    s = scheduled(buyer, service, placed_order, rules=rules, ceiling=ceiling)
    connector.price_multiplier = Decimal("1.30")
    drive(service, at())
    assert run_of(s)["status"] == "disrupted" and run_of(s)["reason_code"] == "CEILING_EXCEEDED"
    assert schedule_row(s)["status"] == "stopped"


def test_an_unavailable_product_without_a_substitute_stops_the_schedule(
    buyer, service, connector, placed_order
):
    s = scheduled(buyer, service, placed_order)
    connector.stock = {"464306": "0"}
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "disrupted" and run["reason_code"] == "PRODUCT_UNAVAILABLE"
    assert run["reason"]["lines"][0]["status"] == "unavailable"
    assert schedule_row(s)["status"] == "stopped"


# --- accepted substitutes (POL-012, CNF-036) ------------------------------------------------


def test_an_accepted_substitute_in_range_is_used_automatically(
    buyer, service, connector, placed_order
):
    widen_scope("464398")
    rules = {"464306": {"accepted_substitutes": ["464398"], "price_range_pct": "5"}}
    s = scheduled(buyer, service, placed_order, rules=rules)
    connector.stock = {"464306": "0"}
    assert drive(service, at()) == 3  # prepare and plan, prepare the substitute, commit
    run = run_of(s)
    assert run["status"] == "committed"
    assert [x["substitute_product_id"] for x in run["substitutions"]] == ["464398"]
    receipt = one("SELECT receipt FROM orders WHERE id=%s", run["order_id"])["receipt"]
    assert receipt["scheduled_run"]["substitutions"][0]["substitute_product_id"] == "464398"
    ordered = one("SELECT request FROM proposal_revisions WHERE proposal_id=%s", run["proposal_id"])
    assert [line["product_id"] for line in ordered["request"]["lines"]] == ["464398"]
    assert schedule_row(s)["status"] == "active"


def test_the_substitute_closest_to_the_original_price_wins(buyer, service, connector, placed_order):
    widen_scope("464398", "463380")
    rules = {"464306": {"accepted_substitutes": ["464398", "463380"], "price_range_pct": "20"}}
    s = scheduled(buyer, service, placed_order, rules=rules)
    connector.stock = {"464306": "0"}
    connector.product_multipliers = {"464398": Decimal("1.15"), "463380": Decimal("1.03")}
    drive(service, at())
    assert [x["substitute_product_id"] for x in run_of(s)["substitutions"]] == ["463380"]


def test_a_substitute_outside_the_range_is_a_disruption(buyer, service, connector, placed_order):
    widen_scope("464398")
    rules = {"464306": {"accepted_substitutes": ["464398"], "price_range_pct": "5"}}
    s = scheduled(buyer, service, placed_order, rules=rules)
    connector.stock = {"464306": "0"}
    connector.product_multipliers = {"464398": Decimal("1.30")}
    drive(service, at())
    assert run_of(s)["status"] == "disrupted" and schedule_row(s)["status"] == "stopped"


def test_an_expensive_original_is_replaced_by_a_cheaper_accepted_substitute(
    buyer, service, connector, placed_order
):
    widen_scope("464398")
    rules = {"464306": {"accepted_substitutes": ["464398"], "price_range_pct": "10"}}
    s = scheduled(buyer, service, placed_order, rules=rules)
    connector.product_multipliers = {"464306": Decimal("1.25")}  # original out of range
    drive(service, at())
    assert [x["substitute_product_id"] for x in run_of(s)["substitutions"]] == ["464398"]
    assert run_of(s)["status"] == "committed"


# --- pause, cancel, expiry, missed dates ----------------------------------------------------


def test_a_paused_schedule_skips_its_dates_and_resumes_from_the_next(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    schedules.pause(buyer, s["id"])
    base = len(orders())
    drive(service, at())
    assert len(orders()) == base
    skipped = run_of(s)
    assert skipped["status"] == "skipped" and skipped["reason_code"] == "PAUSED"
    assert skipped["proposal_id"] is None and not skipped["conversation_id"]
    assert schedule_row(s)["status"] == "paused"
    assert schedule_row(s)["next_run_date"] == TODAY + timedelta(days=1)
    schedules.resume(buyer, s["id"])
    drive(service, at(TODAY + timedelta(days=1)))
    runs = many("SELECT scheduled_date,status FROM scheduled_runs ORDER BY scheduled_date")
    assert [(r["scheduled_date"], r["status"]) for r in runs] == [
        (TODAY, "skipped"),
        (TODAY + timedelta(days=1), "committed"),
    ]
    assert len(orders()) == base + 1


def test_a_long_pause_leaves_one_skipped_run_per_date(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    schedules.pause(buyer, s["id"])
    drive(service, at(TODAY + timedelta(days=4)))
    dates = [r["scheduled_date"] for r in many("SELECT scheduled_date FROM scheduled_runs")]
    assert sorted(dates) == [TODAY + timedelta(days=i) for i in range(5)]
    assert schedule_row(s)["next_run_date"] == TODAY + timedelta(days=5)


def test_a_cancelled_schedule_runs_nothing(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    schedules.cancel(buyer, s["id"])
    assert drive(service, at()) == 0 and run_of(s) is None


def test_a_schedule_is_cancelled_after_its_year(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order, recurrence={"kind": "days", "interval": 30})
    later = schedule_row(s)["valid_until"] + timedelta(days=1)
    assert drive(service, at(later)) == 0
    done = schedule_row(s)
    assert done["status"] == "expired" and done["next_run_date"] is None
    assert one("SELECT count(*) AS n FROM scheduled_runs")["n"] == 0


def test_a_date_that_was_missed_is_a_disruption(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    drive(service, at(TODAY + timedelta(days=2)))
    run = run_of(s)
    assert run["scheduled_date"] == TODAY and run["status"] == "disrupted"
    assert run["reason_code"] == "RUN_MISSED" and schedule_row(s)["status"] == "stopped"


# --- the commit gate ------------------------------------------------------------------------


def scheduler_identity(buyer):
    return one(
        "SELECT i.* FROM scheduler_identities s JOIN identities i ON i.id=s.identity_id "
        "WHERE s.buyer_id=%s",
        buyer["buyer_id"],
    )


def prepared_elsewhere(service, buyer, request_data):
    from aimo.schemas import PrepareRequest

    request_data["idempotency_key"] = str(uuid4())
    return service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )


def commit(service, identity, p, revision=1):
    from aimo.schemas import CommitRequest

    return service.commit_order(
        identity,
        CommitRequest(
            proposal_id=p["proposal_id"], revision=revision, idempotency_key=str(uuid4())
        ),
    )


def test_the_scheduler_cannot_commit_a_proposal_that_belongs_to_no_run(
    buyer, service, request_data
):
    p = prepared_elsewhere(service, buyer, request_data)
    with pytest.raises(Problem) as refused:
        commit(service, scheduler_identity(buyer), p)
    assert refused.value.code in ("SCHEDULE_NOT_AUTHORIZED", "NOT_FOUND")
    assert len(orders()) == 0


def test_the_scheduler_cannot_commit_after_the_customer_cancelled(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())  # prepared
    schedules.cancel(buyer, s["id"])
    before = len(orders())
    assert drive(service, at()) <= 1
    assert len(orders()) == before and run_of(s)["status"] != "committed"


def test_the_gate_itself_refuses_a_direct_commit_after_the_customer_cancelled(
    buyer, service, placed_order
):
    """Not the engine's own check: the scheduler identity calls the Service directly."""
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())
    schedules.cancel(buyer, s["id"])
    run = run_of(s)
    before = len(orders())
    with pytest.raises(Problem) as refused:
        commit(service, scheduler_identity(buyer), {"proposal_id": run["proposal_id"]})
    assert refused.value.code == "SCHEDULE_NOT_AUTHORIZED" and refused.value.status == 403
    assert len(orders()) == before


def test_the_gate_refuses_a_run_that_is_not_prepared(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    drive(service, at())  # committed
    run = run_of(s)
    with pytest.raises(Problem) as refused:
        commit(service, scheduler_identity(buyer), {"proposal_id": run["proposal_id"]})
    assert refused.value.code in ("SCHEDULE_NOT_AUTHORIZED", "ALREADY_COMMITTED", "STALE_REVISION")
    assert len(orders()) == 2


def test_the_gate_refuses_a_prepared_run_whose_proposal_is_not_the_agreed_basket(
    buyer, service, placed_order, request_data
):
    """Defence in depth: even a run row that points at the wrong proposal commits nothing."""
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())
    request_data["lines"] = [{"product_id": "464306", "amount": "20", "unit": "L"}]  # not 10 L
    other = prepared_elsewhere(service, buyer, request_data)
    assert other["policy_outcome"] == "ready_to_commit"
    with connection() as c:
        c.execute(
            "UPDATE scheduled_runs SET proposal_id=%s WHERE authorization_id=%s",
            (other["proposal_id"], s["id"]),
        )
    before = len(orders())
    with pytest.raises(Problem) as refused:
        commit(service, scheduler_identity(buyer), other)
    assert refused.value.code == "SCHEDULE_NOT_AUTHORIZED"
    assert len(orders()) == before


def test_another_buyers_scheduler_cannot_see_the_proposal(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other','999',1)")
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) "
            "SELECT 'other',1,rules FROM policies WHERE buyer_id='demo-hotel'"
        )
        c.execute(
            "INSERT INTO identities VALUES('scheduler:other','other','scheduler',true,'!','{}')"
        )
    foreign = one("SELECT * FROM identities WHERE id='scheduler:other'")
    with pytest.raises(Problem) as refused:
        commit(service, foreign, {"proposal_id": run_of(s)["proposal_id"]})
    assert refused.value.code == "NOT_FOUND"


def test_the_scheduler_cannot_commit_while_the_schedule_is_paused(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())
    schedules.pause(buyer, s["id"])
    before = len(orders())
    drive(service, at())
    assert len(orders()) == before and run_of(s)["status"] == "skipped"


def test_the_gate_refuses_a_prepared_proposal_whose_price_moved(
    buyer, service, connector, placed_order
):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())  # prepared at the agreed price
    connector.price_multiplier = Decimal("1.5")
    before = len(orders())
    drive(service, at())
    assert len(orders()) == before
    assert run_of(s)["status"] == "disrupted" and schedule_row(s)["status"] == "stopped"


# --- failures -------------------------------------------------------------------------------


def test_a_supplier_outage_is_retried_with_backoff_then_a_disruption(
    buyer, service, connector, placed_order, monkeypatch
):
    s = scheduled(buyer, service, placed_order)

    def down(*args, **kwargs):
        raise Problem("UPSTREAM_UNAVAILABLE", "Supplier lookup unavailable.", 503)

    monkeypatch.setattr(connector, "lookup", down)
    moment = at()
    for attempt in range(1, 5):
        assert scheduler.run_due_schedules(service, now=moment) is True
        run = run_of(s)
        assert run["status"] == "due" and run["attempts"] == attempt
        assert run["lease_until"] > moment  # backoff: not picked up again at once
        assert scheduler.run_due_schedules(service, now=moment) is False
        moment = run["lease_until"] + timedelta(seconds=1)
    scheduler.run_due_schedules(service, now=moment)
    run = run_of(s)
    assert run["status"] == "disrupted" and run["reason_code"] == "UPSTREAM_UNAVAILABLE"
    assert schedule_row(s)["status"] == "stopped" and len(orders()) == 1  # only the source order


def test_an_outage_that_recovers_places_exactly_one_order(
    buyer, service, connector, placed_order, monkeypatch
):
    s = scheduled(buyer, service, placed_order)
    real = connector.lookup
    monkeypatch.setattr(
        connector,
        "lookup",
        lambda *a, **k: (_ for _ in ()).throw(Problem("UPSTREAM_RATE_LIMITED", "x", 503)),
    )
    scheduler.run_due_schedules(service, now=at())
    monkeypatch.setattr(connector, "lookup", real)
    moment = run_of(s)["lease_until"] + timedelta(seconds=1)
    drive(service, moment)
    assert run_of(s)["status"] == "committed" and len(orders()) == 2


def test_an_unexpected_error_is_counted_like_an_outage_and_never_loops(
    buyer, service, connector, placed_order, monkeypatch
):
    s = scheduled(buyer, service, placed_order)
    monkeypatch.setattr(connector, "lookup", lambda *a, **k: 1 / 0)
    scheduler.run_due_schedules(service, now=at())
    assert run_of(s)["attempts"] == 1 and run_of(s)["status"] == "due"
    assert scheduler.run_due_schedules(service, now=at()) is False


def test_a_buyer_without_a_scheduler_identity_fails_closed(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    with connection() as c:
        c.execute("DELETE FROM scheduler_identities")
    drive(service, at())
    assert (
        run_of(s)["status"] == "disrupted"
        and run_of(s)["reason_code"] == "SCHEDULER_NOT_CONFIGURED"
    )


def test_each_pass_creates_a_bounded_number_of_runs(buyer, service, placed_order, monkeypatch):
    from aimo.config import settings

    monkeypatch.setattr(settings(), "scheduler_max_runs_per_pass", 2)
    for _ in range(3):
        scheduled(buyer, service, placed_order)
    assert scheduler.materialise(at()) == 2
    assert scheduler.materialise(at()) == 1


def test_a_stored_request_with_a_server_only_constraints_key_still_prepares():
    auth = {
        "id": uuid4(),
        "request": {
            "destination": "hotel-helsinki",
            "lines": [{"product_id": "464306", "amount": "10", "unit": "L"}],
            "constraints": [{"name": "budget_gross", "value": "1", "source": "chat"}],
        },
    }
    run = {"scheduled_date": TODAY, "delivery_date": TODAY + timedelta(days=2)}
    assert "constraints" not in scheduler.basket(auth, run, [])


def test_resume_after_a_worker_outage_skips_the_paused_dates_and_is_not_a_missed_run(
    buyer, service, placed_order, monkeypatch
):
    """Q-90: resume continues from the next date. The paused dates are skipped runs, never RUN_MISSED."""
    s = scheduled(buyer, service, placed_order)
    schedules.pause(buyer, s["id"])
    later = TODAY + timedelta(days=3)  # the worker was down: no pass ran while the dates went by
    with monkeypatch.context() as clock:
        clock.setattr(scheduler, "helsinki_today", lambda now=None: later)
        resumed = schedules.resume(buyer, s["id"])
    before = len(orders())
    assert resumed["status"] == "active" and resumed["next_run_date"] == later + timedelta(days=1)
    skipped = many("SELECT scheduled_date,status,reason_code FROM scheduled_runs ORDER BY 1")
    assert [(r["scheduled_date"], r["status"], r["reason_code"]) for r in skipped] == [
        (TODAY + timedelta(days=d), "skipped", "PAUSED") for d in (0, 1, 2, 3)
    ]
    drive(service, at(later))  # the first pass after the resume
    assert schedule_row(s)["status"] == "active" and len(orders()) == before
    assert not many("SELECT 1 FROM scheduled_runs WHERE reason_code='RUN_MISSED'")
    drive(service, at(later + timedelta(days=1)))  # the next scheduled date places the order
    assert len(orders()) == before + 1
    assert run_of_date(s, later + timedelta(days=1))["status"] == "committed"


def run_of_date(schedule, day):
    return one(
        "SELECT * FROM scheduled_runs WHERE authorization_id=%s AND scheduled_date=%s",
        schedule["id"],
        day,
    )
