"""Independent review of the scheduler (WS-C, PR #189): whose authority a standing order carries.

R-1 the creating approver's own limit applies at creation; R-2 it still applies when the unattended
run commits; R-3 a source order's one-off budget never caps the standing order; R-4 the gate trusts
no substitution it cannot derive from the authorization. Fixture supplier data; every order is a mock.
"""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from test_scheduler_engine import (
    at,
    drive,
    one,
    orders,
    run_of,
    schedule_row,
    scheduled,
    widen_scope,
)
from test_schedules import create_body, preview_body, refused

from aimo import auth, scheduler, schedules
from aimo.db import connection, js
from aimo.schemas import PrepareRequest

pytestmark = pytest.mark.usefixtures("demo_mode")


def second_approver(max_gross, ident="junior"):
    """Another approver of the same buyer with their own limit (the demo buyer keeps 5000)."""
    authority = {
        "currency": "EUR",
        "max_gross": max_gross,
        "exceptions": ["substitution", "overbuy"],
    }
    with connection() as c:
        c.execute(
            "INSERT INTO identities VALUES(%s,'demo-hotel','approver',true,'!no-login',%s)",
            (ident, js(authority)),
        )
        return c.execute("SELECT * FROM identities WHERE id=%s", (ident,)).fetchone()


def make_as(identity, service, order, **changes):
    terms = schedules.preview(identity, preview_body(order), service)
    return schedules.create(identity, create_body(order, terms, **changes), service)


# --- R-1 --------------------------------------------------------------------------------------


def test_an_approver_cannot_authorize_a_standing_order_above_their_own_limit(
    buyer, service, placed_order
):
    junior = second_approver("1.00")
    terms = schedules.preview(junior, preview_body(placed_order), service)
    err = refused(
        "APPROVAL_SCOPE",
        schedules.create,
        junior,
        create_body(placed_order, terms, price_ceiling_gross="4000.00"),
        service,
    )
    assert err.status == 403
    assert one("SELECT count(*) AS n FROM scheduled_authorizations")["n"] == 0


def test_the_limit_applies_to_the_price_ceiling_a_run_may_reach(buyer, service, placed_order):
    mid = second_approver("20.00")  # covers the agreed total (about 17) but not a ceiling of 100
    terms = schedules.preview(mid, preview_body(placed_order), service)
    refused(
        "APPROVAL_SCOPE",
        schedules.create,
        mid,
        create_body(placed_order, terms, price_ceiling_gross="100.00"),
        service,
    )
    ok = schedules.create(
        mid, create_body(placed_order, terms, price_ceiling_gross="20.00"), service
    )
    assert ok["status"] == "active"


def test_a_replace_applies_the_same_limit(buyer, service, placed_order):
    from aimo.schedule_schemas import ScheduleEditPreviewRequest, ScheduleReplaceRequest

    old = make_as(buyer, service, placed_order)
    junior = second_approver("1.00")
    edit = schedules.preview_edit(junior, old["id"], ScheduleEditPreviewRequest(), service)
    body = ScheduleReplaceRequest.model_validate(
        {"agreed_terms_fingerprint": edit["terms_fingerprint"], "idempotency_key": str(uuid4())}
    )
    refused("APPROVAL_SCOPE", schedules.replace, junior, old["id"], body, service)
    assert schedules.get(buyer, old["id"])["status"] == "active"


# --- R-2 --------------------------------------------------------------------------------------


def test_a_run_does_not_commit_after_its_creators_authority_was_cut(buyer, service, placed_order):
    junior = second_approver("5000.00")
    s = make_as(junior, service, placed_order, first_run_date=str(scheduler.helsinki_today()))
    with connection() as c:  # the demo buyer still covers the total, so the policy stays ready
        c.execute(
            "UPDATE identities SET authority=jsonb_set(authority,'{max_gross}','\"1.00\"') WHERE id='junior'"
        )
    before = len(orders())
    drive(service, at())
    assert len(orders()) == before
    assert run_of(s)["status"] == "disrupted"
    assert schedule_row(s)["status"] == "stopped"


# --- R-3 --------------------------------------------------------------------------------------


def test_a_source_orders_one_off_budget_does_not_cap_the_standing_order(
    buyer, service, connector, placed_order
):
    from test_schedules import order_with_server_constraints

    source = order_with_server_constraints(placed_order)
    with connection() as c:  # the old order carried a hard budget of 20.00 for that one purchase
        c.execute("ALTER TABLE proposal_revisions DISABLE TRIGGER immutable_revisions")
        c.execute(
            "UPDATE proposal_revisions SET request=request || %s WHERE proposal_id=%s",
            (js({"budget_gross": "20.00"}), source["proposal_id"]),
        )
        c.execute("ALTER TABLE proposal_revisions ENABLE TRIGGER immutable_revisions")
    rules = {"464306": {"accepted_substitutes": [], "price_range_pct": "50"}}
    s = scheduled(buyer, service, source, rules=rules, ceiling="100.00")
    assert "budget_gross" not in schedule_row(s)["request"]
    connector.price_multiplier = Decimal(
        "1.3"
    )  # 22.10 gross: above the old budget, inside the range
    before = len(orders())
    drive(service, at())
    assert run_of(s)["status"] == "committed" and len(orders()) == before + 1


# --- R-4 --------------------------------------------------------------------------------------


def test_the_gate_does_not_trust_a_substitution_the_authorization_never_accepted(
    buyer, service, placed_order
):
    widen_scope("464398")
    s = scheduled(buyer, service, placed_order)  # no accepted substitutes at all
    auth_row = schedule_row(s)
    plan = [
        {"product_id": "464306", "name": "x", "status": "substituted", "agreed_gross": "1.70",
         "current_gross": "1.70", "substitute_product_id": "464398"}
    ]  # fmt: skip
    run = {
        "scheduled_date": scheduler.helsinki_today(),
        "delivery_date": scheduler.helsinki_today(),
    }
    request = scheduler.basket(auth_row, run, plan) | {"idempotency_key": str(uuid4())}
    proposal = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request)
    )
    verdict = scheduler.compare(
        auth_row,
        proposal["request"],
        deepcopy(proposal["snapshot"]),
        proposal["policy_outcome"],
        plan,
    )
    assert not verdict["ok"] and "RUN_TERMS_CHANGED" in verdict["codes"]
