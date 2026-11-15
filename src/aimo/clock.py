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

from aimo import upstream
from aimo.config import settings
from aimo.db import Problem, connection
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


# --- the per-buyer demo clock -----------------------------------------------------------------------

MAX_JUMP_DAYS = 30  # owner Q-116: per jump
MAX_TOTAL_DAYS = 400  # per buyer, until a reset
DAY = 86400


def enabled():
    """On only when the deployment enables it and supplier lookups are not live."""
    return bool(settings().demo_clock_enabled) and upstream.effective_mode() != "live"


def require_enabled():
    if not enabled():
        raise Problem("NOT_FOUND", "Not found.", 404)


def offset_seconds(buyer_id, c=None):
    if not enabled():
        return 0
    if c is None:
        with connection() as c:
            return offset_seconds(buyer_id, c)
    row = c.execute(
        "SELECT offset_seconds FROM demo_clock WHERE buyer_id=%s", (buyer_id,)
    ).fetchone()
    return row["offset_seconds"] if row else 0


def app_now(buyer_id):
    """The buyer's simulated time: real time plus their offset while the clock is on."""
    return real_now() + timedelta(seconds=offset_seconds(buyer_id))


def label(buyer_id, c=None):
    """`demo` while the buyer's offset is above zero and the clock is on, else `real`."""
    return "demo" if offset_seconds(buyer_id, c) > 0 else "real"


def fulfilment_view(c, buyer_id):
    """`f(delivery_date, accepted_at)`: the simulated status at the buyer's time (offset read once)."""
    offset = offset_seconds(buyer_id, c)
    now = real_now() + timedelta(seconds=offset)
    mode = "demo" if offset > 0 else "real"
    return lambda delivery_date, accepted_at=None: fulfilment(
        delivery_date, now, clock=mode, accepted_at=accepted_at
    )


def _state(real, offset):
    return {
        "enabled": True,
        "real_now": real,
        "demo_now": real + timedelta(seconds=offset),
        "offset_seconds": offset,
        "offset_days": offset // DAY,
        "max_jump_days": MAX_JUMP_DAYS,
        "max_total_days": MAX_TOTAL_DAYS,
    }


def state(buyer_id):
    require_enabled()
    return _state(real_now(), offset_seconds(buyer_id))


def earliest_undelivered(c, buyer_id, now):
    """The delivery date of the buyer's earliest order that is not delivered at `now`, or None."""
    rows = c.execute(
        """SELECT (r.request->>'delivery_date')::date AS delivery_date FROM orders o
        JOIN proposal_revisions r ON r.proposal_id=o.proposal_id AND r.revision=o.revision
        WHERE o.buyer_id=%s ORDER BY 1""",
        (buyer_id,),
    ).fetchall()
    for row in rows:
        if fulfilment(row["delivery_date"], now)["status"] != "delivered":
            return row["delivery_date"]
    return None


def _replay(c, buyer_id, key, kind, days, to):
    """The result of an earlier request with this key, or None. The same key for another request
    is a conflict."""
    old = c.execute(
        "SELECT * FROM demo_clock_events WHERE buyer_id=%s AND idempotency_key=%s", (buyer_id, key)
    ).fetchone()
    if not old:
        return None
    if (old["kind"], old["jump_days"], old["jump_to"]) != (kind, days, to):
        raise Problem("IDEMPOTENCY_CONFLICT", "This key already moved the clock differently.", 409)
    return _state(old["real_at"], old["new_offset_seconds"])


def _write(c, buyer_id, actor_id, key, kind, days, to, old, new, real):
    c.execute(
        """INSERT INTO demo_clock(buyer_id,offset_seconds,updated_at) VALUES(%s,%s,%s)
        ON CONFLICT(buyer_id) DO UPDATE SET offset_seconds=EXCLUDED.offset_seconds,
        updated_at=EXCLUDED.updated_at""",
        (buyer_id, new, real),
    )
    c.execute(
        """INSERT INTO demo_clock_events(buyer_id,actor_id,kind,jump_days,jump_to,old_offset_seconds,
        new_offset_seconds,real_at,idempotency_key) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (buyer_id, actor_id, kind, days, to, old, new, real, key),
    )
    return _state(real, new)


def advance(buyer_id, actor_id, *, days=None, to=None, idempotency_key):
    """Move the buyer's clock forward by `days` (1..30) or to 06:00 Helsinki on the delivery date of
    their earliest undelivered order (`to="delivery_day"`). At most 30 days per jump and 400 days
    in total; forward only. The same key applies once."""
    require_enabled()
    if (days is None) == (to is None):
        raise Problem("INVALID_JUMP", "Give exactly one of days or to.", 422)
    if days is not None and (not isinstance(days, int) or not 1 <= days <= MAX_JUMP_DAYS):
        raise Problem("INVALID_JUMP", f"A jump is 1 to {MAX_JUMP_DAYS} whole days.", 422)
    if to is not None and to != "delivery_day":
        raise Problem("INVALID_JUMP", "The only target is delivery_day.", 422)
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (buyer_id,))
        replay = _replay(c, buyer_id, idempotency_key, "advance", days, to)
        if replay:
            return replay
        old = offset_seconds(buyer_id, c)
        real = real_now()
        now = real + timedelta(seconds=old)
        if days is not None:
            step = days * DAY
        else:
            target_day = earliest_undelivered(c, buyer_id, now)
            if target_day is None:
                raise Problem("NO_PENDING_DELIVERY", "No order is waiting for delivery.", 409)
            target = _start(target_day, OUT_FOR_DELIVERY_FROM)
            if target <= now:
                raise Problem("DEMO_CLOCK_NOT_FORWARD", "The clock is already there.", 409)
            step = -((now - target) // timedelta(seconds=1))  # whole seconds, rounded up
            if step > MAX_JUMP_DAYS * DAY:
                raise Problem(
                    "INVALID_JUMP",
                    f"That delivery day is more than {MAX_JUMP_DAYS} days away; jump in steps.",
                    422,
                )
        if old + step > MAX_TOTAL_DAYS * DAY:
            raise Problem(
                "DEMO_CLOCK_LIMIT", f"At most {MAX_TOTAL_DAYS} days in total; reset the clock.", 409
            )
        return _write(
            c, buyer_id, actor_id, idempotency_key, "advance", days, to, old, old + step, real
        )


def reset(buyer_id, actor_id, *, idempotency_key):
    """Back to real time. Recorded like a jump; the same key applies once."""
    require_enabled()
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (buyer_id,))
        replay = _replay(c, buyer_id, idempotency_key, "reset", None, None)
        if replay:
            return replay
        old = offset_seconds(buyer_id, c)
        return _write(
            c, buyer_id, actor_id, idempotency_key, "reset", None, None, old, 0, real_now()
        )
