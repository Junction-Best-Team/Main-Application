"""PR-agent review of the scheduler (2026-11-15): the customer confirming mid-run, a pause between
prepare and commit, the terms re-checked at run time, and a terms revision that never settles.
Fixture supplier data; every order is a mock."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from test_scheduler_engine import (
    at,
    drive,
    many,
    one,
    orders,
    run_of,
    schedule_row,
    scheduled,
)

from aimo import auth, conversations, scheduler, schedules
from aimo.schemas import CommitRequest
from aimo.service import Service

pytestmark = pytest.mark.usefixtures("demo_mode")


def customer_confirms(service, buyer, proposal_id):
    """The buyer confirms the scheduled proposal in the product (the human route), with a service
    of its own so that a test's patched scheduler commit is not in the way."""
    body = CommitRequest(proposal_id=proposal_id, revision=1, idempotency_key=str(uuid4()))
    return conversations.confirm(buyer, proposal_id, body, Service(service.connector))


# --- (2) an order that already exists, a pause that comes between the steps -------------------


def test_the_customer_confirming_a_prepared_run_is_not_a_disruption(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())  # prepared
    run = run_of(s)
    receipt = customer_confirms(service, buyer, str(run["proposal_id"]))
    before = len(orders())
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "committed" and str(run["order_id"]) == receipt["order_id"]
    assert schedule_row(s)["status"] == "active" and run["conversation_id"] is None
    assert len(orders()) == before  # no second order
    events = [e["event"] for e in many("SELECT event FROM scheduled_run_events ORDER BY id")]
    assert "disrupted" not in events and "committed" in events


def test_an_order_placed_between_the_check_and_the_commit_is_not_a_disruption(
    buyer, service, placed_order, monkeypatch
):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())
    pid = str(run_of(s)["proposal_id"])
    real = service.commit_order

    def customer_gets_there_first(identity, body):
        customer_confirms(service, buyer, pid)  # the human click lands first
        return real(identity, body)  # -> ALREADY_COMMITTED

    monkeypatch.setattr(service, "commit_order", customer_gets_there_first)
    before = len(orders())
    drive(service, at())
    run = run_of(s)
    # exactly one new order: the customer's own, none from the scheduler
    assert run["status"] == "committed" and run["order_id"] and len(orders()) == before + 1
    assert schedule_row(s)["status"] == "active"


def test_a_pause_between_prepare_and_commit_skips_the_run_instead_of_stopping_the_schedule(
    buyer, service, placed_order, monkeypatch
):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())
    real = service.commit_order

    def paused_in_between(identity, body):
        schedules.pause(buyer, s["id"])  # after the engine's own checks, before the gate
        return real(identity, body)

    monkeypatch.setattr(service, "commit_order", paused_in_between)
    before = len(orders())
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "skipped" and run["reason_code"] == "PAUSED"
    assert schedule_row(s)["status"] == "paused" and len(orders()) == before
    assert run["conversation_id"] is None
    cancelled = one("SELECT reason FROM order_request_cancellations")
    assert cancelled["reason"] == "customer_cancelled"


def test_a_cancel_between_prepare_and_commit_skips_the_run(
    buyer, service, placed_order, monkeypatch
):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())
    real = service.commit_order

    def cancelled_in_between(identity, body):
        schedules.cancel(buyer, s["id"])
        return real(identity, body)

    monkeypatch.setattr(service, "commit_order", cancelled_in_between)
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "skipped" and run["reason_code"] in (
        "AUTHORIZATION_CANCELLED",
        "REQUEST_CANCELLED",  # a cancel now also cancels the open proposal (R-15)
    )
    assert schedule_row(s)["status"] == "cancelled"


# --- (3) the terms are re-checked at run time -------------------------------------------------


def sample(buyer, service, placed_order):
    """A real authorization row, the proposal the engine would prepare, its snapshot."""
    s = scheduled(buyer, service, placed_order)
    auth_row = schedule_row(s)
    scheduler.run_due_schedules(service, now=at())
    run = run_of(s)
    proposal = service.get_proposal(auth.internal_agent(buyer), str(run["proposal_id"]))
    return auth_row, proposal["request"], proposal["snapshot"], proposal["policy_outcome"], run


def test_an_unchanged_basket_passes_the_run_time_check(buyer, service, placed_order):
    auth_row, request, snapshot, outcome, run = sample(buyer, service, placed_order)
    assert scheduler.compare(
        auth_row, request, snapshot, outcome, delivery_date=run["delivery_date"]
    )["ok"]


def test_a_changed_quantity_a_deposit_the_destination_or_the_currency_is_a_change_of_terms(
    buyer, service, placed_order
):
    auth_row, request, snapshot, outcome, run = sample(buyer, service, placed_order)

    def changed(**edits):
        req, snap = deepcopy(request), deepcopy(snapshot)
        if "amount" in edits:
            snap["lines"][0]["quantity"]["requested_amount"] = edits["amount"]
        if "sales_quantity" in edits:
            snap["lines"][0]["quantity"]["sales_quantity"] = edits["sales_quantity"]
        if "deposit" in edits:
            snap["lines"][0]["deposit_lines"] = [
                {"material": "demo-deposit", "quantity": "1", "unit": "ST",
                 "priced_sales_quantity": "1", "sales_unit": "ST", "net": "0.10", "gross": "0.13"}
            ]  # fmt: skip
        if "destination" in edits:
            req["destination"] = edits["destination"]
        if "currency" in edits:
            snap["currency"] = edits["currency"]
        if "delivery" in edits:
            req["delivery_date"] = edits["delivery"]
        return scheduler.compare(auth_row, req, snap, outcome, delivery_date=run["delivery_date"])

    for edits in (
        {"amount": "20"},
        {"sales_quantity": "99"},
        {"deposit": True},
        {"destination": "somewhere-else"},
        {"currency": "SEK"},
        {"delivery": "2099-01-01"},
    ):
        verdict = changed(**edits)
        assert not verdict["ok"] and verdict["codes"][0] in (
            "RUN_TERMS_CHANGED",
            "PRODUCT_UNAVAILABLE",
        ), (edits, verdict["codes"])


def test_the_stored_agreement_keeps_the_deposit_structure_of_each_line(
    buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order)
    line = schedule_row(s)["agreed_lines"][0]
    assert "deposits" in line and isinstance(line["deposits"], list)
    assert "deposits" not in schedules.get(buyer, s["id"])["lines"][0]  # internal, not in the API


# --- (4) a terms revision that never settles --------------------------------------------------


def test_a_revision_that_never_settles_ends_in_a_disruption(
    buyer, service, connector, placed_order, monkeypatch
):
    rules = {"464306": {"accepted_substitutes": [], "price_range_pct": "50"}}
    s = scheduled(buyer, service, placed_order, rules=rules, ceiling="100.00")
    scheduler.run_due_schedules(service, now=at())  # prepared at the agreed price
    real = connector.lookup

    def drifting(*args, **kwargs):
        connector.price_multiplier = connector.price_multiplier * Decimal("1.001")
        return real(*args, **kwargs)  # inside the range, but a new fingerprint every time

    monkeypatch.setattr(connector, "lookup", drifting)
    before = len(orders())
    drive(service, at(), limit=40)
    run = run_of(s)
    assert run["status"] == "disrupted" and run["reason_code"] == "TERMS_UNSETTLED"
    assert schedule_row(s)["status"] == "stopped" and len(orders()) == before
    assert run["attempts"] >= 4  # the revisions were counted
