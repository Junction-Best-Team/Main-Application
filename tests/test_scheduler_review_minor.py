"""Independent review of the scheduler (WS-C, PR #189), the smaller holes: a zero agreed price, a
cancel that leaves a run's proposal open, NUL characters and a ceiling the database cannot store."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_scheduler_engine import at, run_of, scheduled
from test_schedules import create_body, make, preview_body

from aimo import scheduler, schedules
from aimo.db import Problem
from aimo.schedule_schemas import (
    LineRule,
    ScheduleCreateRequest,
    SchedulePreviewRequest,
)

pytestmark = pytest.mark.usefixtures("demo_mode")


def test_a_zero_agreed_price_never_crashes_the_comparison():
    assert scheduler.percent_off(Decimal("1.70"), Decimal("0")) > 100  # outside any range
    assert scheduler.percent_off(Decimal("0"), Decimal("0")) == 0  # nothing moved


def test_cancelling_a_schedule_cancels_the_open_proposal_of_its_prepared_run(
    buyer, service, placed_order
):
    s = scheduled(buyer, service, placed_order)
    scheduler.run_due_schedules(service, now=at())  # prepared, the proposal is open
    proposal_id = str(run_of(s)["proposal_id"])
    schedules.cancel(buyer, s["id"])
    with pytest.raises(Problem) as refused:  # the customer's own confirm is refused now
        from aimo import conversations
        from aimo.schemas import CommitRequest

        conversations.confirm(
            buyer,
            proposal_id,
            CommitRequest(proposal_id=proposal_id, revision=1, idempotency_key=str(uuid4())),
            service,
        )
    assert refused.value.code == "REQUEST_CANCELLED"


@pytest.mark.parametrize(
    "build",
    [
        lambda base: SchedulePreviewRequest.model_validate(base | {"title": "a\x00b"}),
        lambda base: ScheduleCreateRequest.model_validate(
            base
            | {
                "price_ceiling_gross": "10",
                "agreed_terms_fingerprint": "a" * 64,
                "idempotency_key": "key-\x00-123",
            }
        ),
        lambda base: ScheduleCreateRequest.model_validate(
            base
            | {
                "price_ceiling_gross": "999999999999.9999",  # numeric(14,2) cannot hold it
                "agreed_terms_fingerprint": "a" * 64,
                "idempotency_key": "key-12345",
            }
        ),
        lambda base: SchedulePreviewRequest.model_validate(
            base | {"line_rules": {"464306": {"accepted_substitutes": ["x\x00y"]}}}
        ),
    ],
)
def test_nul_characters_and_an_unstorable_ceiling_are_refused_by_the_model(build):
    base = {
        "order_id": str(uuid4()),
        "recurrence": {"kind": "days", "interval": 1},
        "first_run_date": "2030-01-01",
    }
    with pytest.raises(ValidationError):
        build(base)
    assert LineRule(accepted_substitutes=["464398"])  # the normal case still passes


def test_the_candidate_lookup_and_the_orders_search_refuse_a_nul_character(buyer, service):
    from aimo import orders_list

    with pytest.raises(Problem) as q:
        orders_list.orders_page(buyer, 0, 20, query="a\x00b")
    assert q.value.status == 422 and q.value.code == "INVALID_ORDER_QUERY"
    with pytest.raises(Problem) as p:
        schedules.substitute_candidates(buyer, "46\x006", service)
    assert p.value.status == 422


def test_a_normal_schedule_still_works(buyer, service, placed_order):
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    made = schedules.create(buyer, create_body(placed_order, terms), service)
    assert made["status"] == "active" and make
