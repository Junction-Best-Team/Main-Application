"""Engineering guard (not an owner rule): a lookup's delivery date must be a plausible date.

`0001-01-01` is a valid ISO date but crashed the supplier call path and was reported to the agent as
a transient fault ("Retry later"). LookupRequest now rejects dates outside 2000-01-01 .. 2100-12-31
with an error that names the field and the limit (JNP3-TCT-003). The window is deliberately fixed,
not tied to today's date, because fixtures and tests use fixed dates.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from aimo.schemas import LookupRequest


def request(day):
    return LookupRequest(product_ids=["464306"], delivery_date=day)


@pytest.mark.parametrize("day", ["2000-01-01", "2026-11-16", "2100-12-31", date(2050, 6, 1)])
def test_plausible_dates_are_accepted(day):
    assert request(day).delivery_date


@pytest.mark.parametrize("day", ["0001-01-01", "1999-12-31", "2101-01-01", "9999-12-31"])
def test_implausible_dates_are_rejected_naming_the_field_and_the_limit(day):
    with pytest.raises(ValidationError) as error:
        request(day)
    problem = error.value.errors()[0]
    assert problem["loc"] == ("delivery_date",)
    assert "2000-01-01" in problem["msg"] or "2100-12-31" in problem["msg"]
