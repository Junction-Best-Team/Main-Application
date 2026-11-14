"""The simulated fulfilment status and the per-buyer demo clock (JNP3-FUL-001..005, CLK-001..008).

Everything here is a MOCK: the supplier has no order API, so an order is never really picked,
shipped or delivered. The status is DERIVED from the order's delivery date and a clock, never
stored (`orders` is append-only), and every result says `simulated: True`.

The demo clock is a separate, narrow clock: `app_now(buyer_id)` is real time plus that buyer's
offset, but only while `DEMO_CLOCK_ENABLED` is on and the supplier mode is not live. It is read by
the fulfilment status and the scheduler's dates and by nothing else: sessions, proposal and
approval expiry, price validity, supplier calls, rate limits and audit timestamps stay on real time
(`aimo.db.now()` is not changed). `real_now()` is the only place this module reads real time.
"""

from datetime import date, datetime, time, timedelta, timezone

from aimo.upstream import HELSINKI

# Owner Q-110: the four states and their start times, with D the delivery date (Europe/Helsinki).
# Named constants in one place; the thresholds can later come from the supplier cutoff.
PREPARING_FROM = (-1, time(0, 0))  # D-1 00:00
OUT_FOR_DELIVERY_FROM = (0, time(6, 0))  # D 06:00
DELIVERED_FROM = (0, time(12, 0))  # D 12:00 (final)

STATES = ("accepted", "preparing", "out_for_delivery", "delivered")


def real_now():
    return datetime.now(timezone.utc)


def _start(delivery_date, rule):
    days, at = rule
    return datetime.combine(delivery_date + timedelta(days=days), at, tzinfo=HELSINKI)


def fulfilment(delivery_date: date, now: datetime, *, clock="real", accepted_at=None):
    """The simulated status of an order delivering on `delivery_date` at time `now`.

    `accepted` until D-1 00:00, `preparing` from then, `out_for_delivery` from D 06:00, `delivered`
    from D 12:00 and for ever. Same-day delivery skips the states already passed (the status is the
    latest one whose start is not after `now`). `since` is when the state began (the accept time for
    `accepted` when the caller knows it, otherwise None); delivered is final (no next state).
    """
    if now.tzinfo is None:
        raise ValueError("fulfilment needs a timezone-aware time")
    starts = [
        ("accepted", accepted_at),
        ("preparing", _start(delivery_date, PREPARING_FROM)),
        ("out_for_delivery", _start(delivery_date, OUT_FOR_DELIVERY_FROM)),
        ("delivered", _start(delivery_date, DELIVERED_FROM)),
    ]
    index = max(i for i, (_, begins) in enumerate(starts) if i == 0 or begins <= now)
    status, since = starts[index]
    following = starts[index + 1] if index + 1 < len(starts) else (None, None)
    return {
        "status": status,
        "since": since,
        "next_status": following[0],
        "next_at": following[1],
        "simulated": True,
        "clock": clock,
    }
