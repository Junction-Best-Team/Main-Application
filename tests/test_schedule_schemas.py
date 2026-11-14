"""The wire shape of the scheduled-order models (person 1's UI and the routes build on these)."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aimo import scheduler
from aimo.schedule_schemas import (
    LineRule,
    Recurrence,
    ScheduleCreateRequest,
    ScheduleDetail,
    ScheduleReplaceRequest,
)

PRESETS = [
    {"kind": "weekdays", "weekdays": [4], "every_weeks": 1},
    {"kind": "weekdays", "weekdays": [1, 4], "every_weeks": 1},
    {"kind": "weekdays", "weekdays": [4], "every_weeks": 2},
    {"kind": "days", "interval": 4},
]


@pytest.mark.parametrize("preset", PRESETS)
def test_the_documented_presets_are_valid_for_the_model_and_the_scheduler(preset):
    dumped = Recurrence.model_validate(preset).model_dump(exclude_none=True)
    assert scheduler.normalize_recurrence(dumped)["kind"] == preset["kind"]
    assert scheduler.next_dates(dumped, date(2026, 11, 20), date(2027, 11, 20), limit=2)


def test_create_needs_the_agreed_fingerprint_a_ceiling_and_a_key():
    body = {
        "order_id": "00000000-0000-0000-0000-000000000001",
        "recurrence": PRESETS[0],
        "first_run_date": "2026-11-20",
        "price_ceiling_gross": "120.00",
        "agreed_terms_fingerprint": "a" * 64,
        "idempotency_key": "create-key-1",
        "line_rules": {"464306": {"accepted_substitutes": ["464398"], "price_range_pct": "7.5"}},
    }
    request = ScheduleCreateRequest.model_validate(body)
    assert request.line_rules["464306"].price_range_pct == Decimal("7.5")
    for missing in ("price_ceiling_gross", "agreed_terms_fingerprint", "idempotency_key"):
        with pytest.raises(ValidationError):
            ScheduleCreateRequest.model_validate({k: v for k, v in body.items() if k != missing})
    with pytest.raises(ValidationError):
        ScheduleCreateRequest.model_validate(body | {"surprise": 1})


@pytest.mark.parametrize(
    "rule",
    [
        {"price_range_pct": "100.01"},
        {"price_range_pct": "-1"},
        {"accepted_substitutes": [str(i) for i in range(6)]},
    ],
)
def test_line_rules_are_bounded(rule):
    with pytest.raises(ValidationError):
        LineRule.model_validate(rule)


def test_replace_may_change_only_what_the_edit_page_changes():
    body = {"agreed_terms_fingerprint": "b" * 64, "idempotency_key": "replace-key-1"}
    assert ScheduleReplaceRequest.model_validate(body).recurrence is None
    assert "runs" in ScheduleDetail.model_fields and "last_run" in ScheduleDetail.model_fields
