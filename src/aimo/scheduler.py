"""Scheduled (standing) re-orders, WS-E. Every order placed here is a MOCK order.

Only the commit guard exists so far. It fails closed: no scheduled authorization or run exists
yet, so the scheduler identity can commit nothing. The run engine replaces this body.
"""

from datetime import timedelta

from aimo.db import Problem, fingerprint

ONE_DAY = timedelta(days=1)


def ensure_commit_allowed(c, identity, p, r, snapshot, evaluated):
    raise Problem(
        "SCHEDULE_NOT_AUTHORIZED",
        "A scheduler identity commits only against a valid scheduled authorization.",
        403,
    )


# --- Terms fingerprint ---------------------------------------------------------------------
# "The same terms" of a standing order. material_fingerprint (purchases.py) cannot be used: it
# hashes request_id, delivery_date, supplier cutoff and full product facts, so two runs on
# different dates never match. The field set is these constants only; widening it (for example
# adding product facts, owner question Q-80) is a change here and nowhere else.
TERMS_REQUEST_FIELDS = ("destination",)
TERMS_LINE_FIELDS = ("product_id", "substitutes_for", "quantity", "deposits", "price", "deleted")
TERMS_QUANTITY_FIELDS = ("requested_amount", "requested_unit", "sales_unit", "sales_quantity")
TERMS_DEPOSIT_FIELDS = (
    "material",
    "quantity",
    "unit",
    "priced_sales_quantity",
    "sales_unit",
    "net",
    "gross",
)
TERMS_PRICE_FIELDS = ("net", "gross", "tax_rate")


def terms_view(request, snapshot):
    """The commercial terms of one proposal revision, free of dates, times, stock and facts."""
    lines = []
    for line in snapshot["lines"]:
        evidence = line["commercial_evidence"]
        values = {
            "product_id": line["product_id"],
            "substitutes_for": line.get("substitutes_for"),
            "quantity": {k: line["quantity"].get(k) for k in TERMS_QUANTITY_FIELDS},
            "deposits": [
                {k: d.get(k) for k in TERMS_DEPOSIT_FIELDS} for d in line["deposit_lines"]
            ],
            "price": {k: evidence.get(k) for k in TERMS_PRICE_FIELDS},
            "deleted": bool(line["product_evidence"].get("deleted")),
        }
        lines.append({k: values[k] for k in TERMS_LINE_FIELDS})
    return {
        **{k: request.get(k) for k in TERMS_REQUEST_FIELDS},
        "currency": snapshot["currency"],
        "lines": sorted(lines, key=lambda line: line["product_id"]),
    }


def terms_fingerprint(request, snapshot):
    return fingerprint(terms_view(request, snapshot))


# --- Recurrence ----------------------------------------------------------------------------
# {"kind": "days", "interval": 4}                    every 4 days from the first run date
# {"kind": "weekdays", "weekdays": [1, 4], "every_weeks": 1}   Tue and Fri (0 = Monday)
# The series starts at first_run_date and never goes past valid_until.
MAX_INTERVAL_DAYS = 365
MAX_EVERY_WEEKS = 52


def normalize_recurrence(recurrence):
    bad = Problem("INVALID_RECURRENCE", "Choose a supported delivery pattern.", 422)
    if not isinstance(recurrence, dict):
        raise bad
    kind = recurrence.get("kind")
    if kind == "days":
        interval = recurrence.get("interval")
        if type(interval) is not int or not 1 <= interval <= MAX_INTERVAL_DAYS:
            raise bad
        return {"kind": "days", "interval": interval}
    if kind == "weekdays":
        days, weeks = recurrence.get("weekdays"), recurrence.get("every_weeks", 1)
        if (
            not isinstance(days, list)
            or not days
            or any(type(d) is not int or not 0 <= d <= 6 for d in days)
            or type(weeks) is not int
            or not 1 <= weeks <= MAX_EVERY_WEEKS
        ):
            raise bad
        return {"kind": "weekdays", "weekdays": sorted(set(days)), "every_weeks": weeks}
    raise bad


def next_dates(recurrence, first_run_date, valid_until, *, after=None, limit=1):
    """The next `limit` scheduled dates strictly after `after` (all from the start if None),
    never before first_run_date and never after valid_until. Pure: no clock, no database."""
    rule = normalize_recurrence(recurrence)
    found, day = [], first_run_date if after is None else max(first_run_date, after + ONE_DAY)
    if rule["kind"] == "days":
        steps = -(-(day - first_run_date).days // rule["interval"])  # ceiling
        day = first_run_date + timedelta(days=steps * rule["interval"])
    first_monday = first_run_date - timedelta(days=first_run_date.weekday())
    while day <= valid_until and len(found) < limit:
        if rule["kind"] == "days":
            found.append(day)
            day += timedelta(days=rule["interval"])
            continue
        week = ((day - timedelta(days=day.weekday())) - first_monday).days // 7
        if day.weekday() in rule["weekdays"] and week % rule["every_weeks"] == 0:
            found.append(day)
        day += ONE_DAY
    return found
