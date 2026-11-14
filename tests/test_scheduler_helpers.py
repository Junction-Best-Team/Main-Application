"""JNP3-CNF-024/026/032: the pure helpers of the scheduler (no engine, no migration yet).

`terms_fingerprint` is "the same terms" of a standing order: stable across dates and request ids,
sensitive to anything the customer agreed (products, quantities, deposits, unit prices,
destination, currency). `next_dates` is the recurrence. Fixture supplier data only.
"""

from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

import pytest

from aimo import auth, scheduler
from aimo.db import Problem
from aimo.schemas import PrepareRequest


def prepare(service, buyer, request_data, **changes):
    request_data = deepcopy(request_data) | {"idempotency_key": str(uuid4())} | changes
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    return p["request"], p["snapshot"]


# --- terms fingerprint ---------------------------------------------------------------------


def test_same_terms_on_another_date_and_request_id_have_the_same_fingerprint(
    service, buyer, request_data
):
    first = prepare(service, buyer, request_data)
    later = prepare(
        service,
        buyer,
        request_data,
        request_id="Standing order, next week",
        delivery_date=str(date.today() + timedelta(days=9)),
    )
    assert first[0]["request_id"] != later[0]["request_id"]
    assert first[0]["delivery_date"] != later[0]["delivery_date"]
    assert scheduler.terms_fingerprint(*first) == scheduler.terms_fingerprint(*later)


def test_stock_level_and_observation_time_do_not_change_the_terms(
    service, connector, buyer, request_data
):
    first = prepare(service, buyer, request_data)
    connector.stock = {"464306": "123"}
    second = prepare(service, buyer, request_data)
    assert scheduler.terms_fingerprint(*first) == scheduler.terms_fingerprint(*second)


def test_a_price_change_changes_the_terms(service, connector, buyer, request_data):
    first = prepare(service, buyer, request_data)
    connector.price_multiplier = connector.price_multiplier * 11 / 10
    second = prepare(service, buyer, request_data)
    assert scheduler.terms_fingerprint(*first) != scheduler.terms_fingerprint(*second)


def test_a_quantity_change_changes_the_terms(service, buyer, request_data):
    first = prepare(service, buyer, request_data)
    more = prepare(
        service, buyer, request_data, lines=[{"product_id": "464306", "amount": "20", "unit": "L"}]
    )
    assert scheduler.terms_fingerprint(*first) != scheduler.terms_fingerprint(*more)


def test_another_product_changes_the_terms(service, buyer, request_data):
    first = prepare(service, buyer, request_data)
    other = prepare(
        service, buyer, request_data, lines=[{"product_id": "464398", "amount": "10", "unit": "L"}]
    )
    assert scheduler.terms_fingerprint(*first) != scheduler.terms_fingerprint(*other)


def test_destination_and_currency_are_terms(service, buyer, request_data):
    request, snapshot = prepare(service, buyer, request_data)
    base = scheduler.terms_fingerprint(request, snapshot)
    assert scheduler.terms_fingerprint(request | {"destination": "elsewhere"}, snapshot) != base
    assert scheduler.terms_fingerprint(request, snapshot | {"currency": "SEK"}) != base


def test_deposits_are_terms(service, buyer, request_data):
    request, snapshot = prepare(service, buyer, request_data)
    with_deposit = deepcopy(snapshot)
    with_deposit["lines"][0]["deposit_lines"] = [
        {"material": "demo-deposit", "quantity": "1", "unit": "PCS", "net": "0.10", "gross": "0.13"}
    ]
    assert scheduler.terms_fingerprint(request, with_deposit) != scheduler.terms_fingerprint(
        request, snapshot
    )


def test_line_order_does_not_matter(service, buyer, request_data):
    request, snapshot = prepare(
        service,
        buyer,
        request_data,
        lines=[
            {"product_id": "464306", "amount": "10", "unit": "L"},
            {"product_id": "464398", "amount": "10", "unit": "L"},
        ],
    )
    swapped = snapshot | {"lines": list(reversed(snapshot["lines"]))}
    assert scheduler.terms_fingerprint(request, swapped) == scheduler.terms_fingerprint(
        request, snapshot
    )


def test_the_field_set_is_one_set_of_constants(service, buyer, request_data, monkeypatch):
    """Widening the terms (owner question Q-80) is a change to the constants only."""
    request, snapshot = prepare(service, buyer, request_data)
    before = scheduler.terms_fingerprint(request, snapshot)
    monkeypatch.setattr(scheduler, "TERMS_PRICE_FIELDS", ("net", "gross"))
    assert scheduler.terms_fingerprint(request, snapshot) != before
    assert set(scheduler.terms_view(request, snapshot)["lines"][0]) == set(
        scheduler.TERMS_LINE_FIELDS
    )


# --- recurrence ----------------------------------------------------------------------------

FRI = date(2026, 11, 20)  # a Friday
END = FRI + timedelta(days=365)


def series(rule, first=FRI, end=END, **kw):
    return scheduler.next_dates(rule, first, end, **kw)


def test_weekly_every_friday():
    rule = {"kind": "weekdays", "weekdays": [4]}
    assert series(rule, limit=3) == [FRI, FRI + timedelta(7), FRI + timedelta(14)]
    assert series(rule, after=FRI, limit=1) == [FRI + timedelta(7)]


def test_twice_weekly_tuesday_and_friday():
    rule = {"kind": "weekdays", "weekdays": [1, 4]}
    got = series(rule, limit=4)
    assert got == [FRI, date(2026, 11, 24), date(2026, 11, 27), date(2026, 12, 1)]


def test_every_other_friday():
    rule = {"kind": "weekdays", "weekdays": [4], "every_weeks": 2}
    assert series(rule, limit=3) == [FRI, FRI + timedelta(14), FRI + timedelta(28)]
    assert series(rule, after=FRI + timedelta(7), limit=1) == [FRI + timedelta(14)]


def test_every_four_days_from_the_first_run_date():
    rule = {"kind": "days", "interval": 4}
    assert series(rule, limit=3) == [FRI, FRI + timedelta(4), FRI + timedelta(8)]
    # `after` in the middle of a period lands on the next multiple, not on after + 4.
    assert series(rule, after=FRI + timedelta(5), limit=1) == [FRI + timedelta(8)]
    assert series(rule, after=FRI - timedelta(30), limit=1) == [FRI]


def test_a_weekday_series_starts_at_the_first_matching_day():
    thursday = FRI - timedelta(1)
    assert series({"kind": "weekdays", "weekdays": [4]}, first=thursday, limit=1) == [FRI]


@pytest.mark.parametrize(
    "rule", [{"kind": "days", "interval": 1}, {"kind": "weekdays", "weekdays": [0, 4]}]
)
def test_the_series_never_passes_valid_until(rule):
    end = FRI + timedelta(30)
    got = scheduler.next_dates(rule, FRI, end, limit=1000)
    assert got and max(got) <= end
    assert scheduler.next_dates(rule, FRI, end, after=end, limit=5) == []
    assert scheduler.next_dates(rule, FRI, FRI - timedelta(1), limit=5) == []


def test_a_year_of_weekly_runs_is_53_dates():
    got = series({"kind": "weekdays", "weekdays": [4]}, limit=1000)
    assert got == [FRI + timedelta(weeks=i) for i in range(53)]  # 364 days <= 365


@pytest.mark.parametrize(
    "rule",
    [
        None,
        {},
        {"kind": "monthly"},
        {"kind": "days", "interval": 0},
        {"kind": "days", "interval": 366},
        {"kind": "days", "interval": True},
        {"kind": "days", "interval": "4"},
        {"kind": "weekdays", "weekdays": []},
        {"kind": "weekdays", "weekdays": [7]},
        {"kind": "weekdays", "weekdays": [4], "every_weeks": 0},
        {"kind": "weekdays", "weekdays": ["fri"]},
    ],
)
def test_an_unsupported_pattern_is_refused(rule):
    with pytest.raises(Problem) as refused:
        scheduler.normalize_recurrence(rule)
    assert (refused.value.code, refused.value.status) == ("INVALID_RECURRENCE", 422)


def test_normalizing_is_stable():
    rule = scheduler.normalize_recurrence({"kind": "weekdays", "weekdays": [4, 1, 4]})
    assert rule == {"kind": "weekdays", "weekdays": [1, 4], "every_weeks": 1}
    assert scheduler.normalize_recurrence(rule) == rule
