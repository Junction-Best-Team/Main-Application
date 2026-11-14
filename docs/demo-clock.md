# Demo clock and simulated fulfilment (MOCK)

The supplier has no order API, so an order is never really picked, shipped or delivered. Every
order shows a **simulated** fulfilment status, derived on read from its delivery date `D`
(Europe/Helsinki) and a clock; it is never stored (`orders` is append-only) and `order_status`
stays `accepted_mock`.

| Status | From |
|---|---|
| `accepted` | the order is placed |
| `preparing` | D-1 00:00 |
| `out_for_delivery` | D 06:00 |
| `delivered` (final) | D 12:00 |

The thresholds are named constants in `src/aimo/clock.py`. The `fulfilment` field
(`status, since, next_status, next_at, simulated: true, clock: "real"|"demo"`) is on proposals
(null until an order exists), the receipt (which also gains `delivery_date` and `destination`) and
`placed` rows of `GET /api/orders`.

## The demo clock

Off by default. With `DEMO_CLOCK_ENABLED=true` each buyer has an offset on top of real time, read by
the fulfilment status and the scheduler only. Sessions, proposal and approval expiry, price validity,
confirmation windows, supplier calls and audit timestamps stay on real time. The app refuses to
start with it on while supplier lookups are live; the hosted fixture deployment may enable it.

- `GET /api/demo/clock`: offset and simulated time.
- `POST /api/demo/clock/advance` `{days: 1..30}` or `{to: "delivery_day"}` (06:00 Helsinki on the
  delivery date of the earliest undelivered order), plus an `idempotency_key`. Forward only, at
  most 30 days per jump and 400 days in total per buyer (409 `DEMO_CLOCK_LIMIT`).
- `POST /api/demo/clock/reset` returns to real time.

All three answer 404 while the clock is disabled. Jumps and resets are recorded in the append-only
`demo_clock_events` (migration `025_demo_clock.sql`).

## The scheduler follows the buyer's clock

`scheduler.run_due_schedules` with no `now` (the worker) judges each standing order by its buyer's
simulated Helsinki date. After a jump every date the jump skipped runs in date order, each at its own
run time, with no `RUN_MISSED` and no `RAN_LATE`. A passed-in `now`, or the clock off, takes the
unchanged path. Leases, retries, prepare and commit stay on real time.
