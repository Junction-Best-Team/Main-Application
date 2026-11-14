"""Independent review of the scheduler (WS-C, PR #189), R-6 to R-10: races, one cancelled request,
the orders list, a long title, a paused schedule that is replaced. Fixture data; mock orders."""

from threading import Thread
from uuid import uuid4

import pytest
from test_scheduler_engine import at, drive, many, one, orders, run_of, schedule_row, scheduled
from test_schedules import make, refused

from aimo import auth, cancellations, conversations, schedules
from aimo.db import Problem, connection
from aimo.schedule_schemas import ScheduleEditPreviewRequest, ScheduleReplaceRequest
from aimo.schemas import DecisionRequest, PrepareRequest

pytestmark = pytest.mark.usefixtures("demo_mode")


def replace_body(buyer, service, schedule_id, **changes):
    edit = schedules.preview_edit(buyer, schedule_id, ScheduleEditPreviewRequest(), service)
    return ScheduleReplaceRequest.model_validate(
        {
            "agreed_terms_fingerprint": edit["terms_fingerprint"],
            "idempotency_key": str(uuid4()),
        }
        | changes
    )


# --- R-6: replace races ------------------------------------------------------------------------


def test_concurrent_replaces_of_one_schedule_have_one_winner(buyer, service, placed_order):
    old = make(buyer, service, placed_order)
    bodies = [replace_body(buyer, service, old["id"]) for _ in range(5)]
    results = []

    def attempt(body):
        try:
            results.append(("ok", schedules.replace(buyer, old["id"], body, service)["id"]))
        except Problem as err:
            results.append(("refused", err.code))

    threads = [Thread(target=attempt, args=(b,)) for b in bodies]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [r[0] for r in results].count("ok") == 1, results
    assert all(r[1] == "SCHEDULE_NOT_ACTIVE" for r in results if r[0] == "refused")
    active = one("SELECT count(*) AS n FROM scheduled_authorizations WHERE status='active'")["n"]
    assert active == 1


def test_a_replace_of_a_stopped_schedule_that_was_already_replaced_is_refused(
    buyer, service, placed_order
):
    old = make(buyer, service, placed_order)
    with connection() as c:
        c.execute(
            "UPDATE scheduled_authorizations SET status='stopped',stop_reason='RUN_MISSED',"
            "next_run_date=NULL WHERE id=%s",
            (old["id"],),
        )
    first = replace_body(buyer, service, old["id"])
    schedules.replace(buyer, old["id"], first, service)
    refused(
        "SCHEDULE_NOT_ACTIVE",
        schedules.replace,
        buyer,
        old["id"],
        replace_body(buyer, service, old["id"]),
        service,
    )
    assert one("SELECT count(*) AS n FROM scheduled_authorizations")["n"] == 2


def test_a_cancel_that_lands_during_a_replace_is_not_undone(
    buyer, service, placed_order, monkeypatch
):
    old = make(buyer, service, placed_order)
    body = replace_body(buyer, service, old["id"])
    real = schedules.build_terms

    def cancelled_while_building(*args, **kwargs):
        terms = real(*args, **kwargs)
        schedules.cancel(buyer, old["id"])  # after replace's first look, before its lock
        return terms

    monkeypatch.setattr(schedules, "build_terms", cancelled_while_building)
    refused("SCHEDULE_NOT_ACTIVE", schedules.replace, buyer, old["id"], body, service)
    assert one("SELECT count(*) AS n FROM scheduled_authorizations WHERE status='active'")["n"] == 0
    assert schedules.get(buyer, old["id"])["status"] == "cancelled"


# --- R-7: one cancelled run request keeps the series --------------------------------------------


def test_cancelling_one_pending_run_request_skips_that_run_and_keeps_the_schedule(
    buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order)
    from aimo import scheduler

    scheduler.run_due_schedules(service, now=at())  # prepared
    proposal_id = str(run_of(s)["proposal_id"])
    cancellations.cancel_my_request(buyer, proposal_id)
    before = len(orders())
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "skipped" and run["reason_code"] == "REQUEST_CANCELLED"
    assert run["conversation_id"] is None and len(orders()) == before
    assert schedule_row(s)["status"] == "active"
    drive(
        service,
        at(
            run["scheduled_date"].replace(day=run["scheduled_date"].day)
            + __import__("datetime").timedelta(days=1)
        ),
    )
    assert one("SELECT count(*) AS n FROM scheduled_runs WHERE status='committed'")["n"] == 1


# --- R-8: the orders list ------------------------------------------------------------------------


def test_requests_that_can_never_be_confirmed_are_not_listed_as_pending(
    buyer, service, request_data
):
    from aimo import orders_list

    def prepared(**changes):
        body = request_data | {"idempotency_key": str(uuid4())} | changes
        return service.prepare_order(
            auth.internal_agent(buyer), PrepareRequest.model_validate(body)
        )

    ok = prepared()
    denied = prepared(budget_gross="1")  # HARD_BUDGET_EXCEEDED
    unresolved = prepared(lines=[{"product_id": "464306", "amount": "10000", "unit": "L"}])
    approval = prepared(lines=[{"product_id": "464398", "amount": "10", "unit": "L"}])
    approval_id = approval["approval_id"]
    from aimo import approval_workflow as workflow

    workflow.record_human_decision(
        buyer, approval_id, DecisionRequest(revision=1, decision="reject")
    )
    shown = {
        item["proposal_id"]: item["status"]
        for item in orders_list.orders_page(buyer, 0, 50)["items"]
        if item["proposal_id"]
    }
    assert shown.get(ok["proposal_id"]) == "pending"
    for blocked in (denied, unresolved, approval):
        assert shown.get(blocked["proposal_id"]) != "pending", blocked["policy_outcome"]


# --- R-9 / R-10 ---------------------------------------------------------------------------------


def test_a_long_source_label_is_cut_to_the_title_limit(buyer, service, request_data):
    request_data["request_id"] = "L" * 100
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    from aimo.schemas import CommitRequest

    receipt = conversations.confirm(
        buyer,
        p["proposal_id"],
        CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4())),
        service,
    )
    made = make(buyer, service, {"order_id": receipt["order_id"]})
    assert 1 <= len(made["title"]) <= 80


def test_replacing_a_paused_schedule_leaves_the_new_one_paused(buyer, service, placed_order):
    old = make(buyer, service, placed_order)
    schedules.pause(buyer, old["id"])
    new = schedules.replace(
        buyer,
        old["id"],
        replace_body(buyer, service, old["id"], title="Renamed for the holiday"),
        service,
    )
    assert new["status"] == "paused" and new["paused_at"]
    drive(service, at())
    assert not many("SELECT 1 FROM scheduled_runs WHERE status='committed'")
