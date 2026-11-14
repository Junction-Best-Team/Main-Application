"""POL-008 for scheduled runs (owner Q-97): the agreed ceiling and diet are trusted constraints.

The run's proposal is prepared with source `scheduled_request` constraints: the price ceiling as
the hard budget and the authorized request's lactose-free / milk-free requirements. The policy
engine then refuses a basket that loosens them, in addition to the engine's own comparison.
"""

from decimal import Decimal

import pytest
from test_scheduler_engine import (
    DAILY,
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

from aimo import scheduler

pytestmark = pytest.mark.usefixtures("demo_mode")  # these tests start schedules today


def stored_request(run):
    return one(
        "SELECT request FROM proposal_revisions WHERE proposal_id=%s AND revision=1",
        run["proposal_id"],
    )["request"]


def test_a_scheduled_proposal_carries_the_ceiling_and_the_diet_as_constraints(
    buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order, ceiling="100.00")
    assert scheduler.run_due_schedules(service, now=at()) is True
    constraints = {c["name"]: c for c in stored_request(run_of(s))["constraints"]}
    assert constraints["budget_gross"] == {
        "name": "budget_gross",
        "value": "100.00",
        "source": "scheduled_request",
        "confirmed": True,
    }
    wanted = (schedule_row(s)["request"] or {}).get("requirements") or {}
    for flag in ("lactose_free", "milk_free"):
        assert (flag in constraints) == bool(wanted.get(flag))


def test_run_constraints_use_only_the_agreed_ceiling_and_the_required_flags():
    auth = {
        "price_ceiling_gross": Decimal("250.50"),
        "request": {"requirements": {"lactose_free": True, "milk_free": False}},
    }
    assert scheduler.run_constraints(auth) == [
        {
            "name": "budget_gross",
            "value": "250.50",
            "source": "scheduled_request",
            "confirmed": True,
        },
        {"name": "lactose_free", "value": True, "source": "scheduled_request", "confirmed": True},
    ]
    assert len(scheduler.run_constraints({"price_ceiling_gross": 5, "request": None})) == 1


def test_a_price_above_the_ceiling_is_refused_by_policy_and_the_schedule_still_stops(
    buyer, service, connector, placed_order
):
    rules = {"464306": {"accepted_substitutes": [], "price_range_pct": "100"}}
    s = scheduled(buyer, service, placed_order, rules=rules, ceiling="19.00")
    connector.price_multiplier = Decimal("2")
    base = len(orders())
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "disrupted" and run["reason_code"] == "CEILING_EXCEEDED"
    assert schedule_row(s)["status"] == "stopped" and len(orders()) == base
    outcome = one(
        "SELECT policy_outcome, reasons FROM proposal_revisions WHERE proposal_id=%s AND revision=1",
        run["proposal_id"],
    )
    assert outcome["policy_outcome"] == "denied"
    assert "HARD_BUDGET_EXCEEDED" in {r["code"] for r in outcome["reasons"]}


def test_an_unchanged_run_still_commits(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    before = len(orders())
    assert drive(service, at()) == 2
    assert run_of(s)["status"] == "committed" and len(orders()) == before + 1
    assert many("SELECT id FROM scheduled_runs")
    assert DAILY and TODAY


def test_a_source_order_with_its_own_limits_still_makes_a_runnable_standing_order(
    buyer, service, placed_order
):
    """The old order's limits (a `constraints` key in its stored request) are never carried over:
    the run's limits are the ceiling and diet the customer agreed for the schedule."""
    from test_schedules import order_with_server_constraints

    source = order_with_server_constraints(placed_order)
    s = scheduled(buyer, service, source, ceiling="100.00")
    assert "constraints" not in schedule_row(s)["request"]
    before = len(orders())
    assert drive(service, at()) == 2
    run = run_of(s)
    assert run["status"] == "committed" and len(orders()) == before + 1
    sent = {c["name"]: c for c in stored_request(run)["constraints"]}
    assert sent["budget_gross"]["value"] == "100.00"
    assert sent["budget_gross"]["source"] == "scheduled_request"
