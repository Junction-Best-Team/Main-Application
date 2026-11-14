# Standing orders (scheduler)

The customer approves exact terms once and the worker re-places that order on a schedule. Every order
it places is a **mock** ("Accepted by demo order service"; no supplier order, no reservation). Design
and decisions: [scheduler-design.md](scheduler-design.md) (read its status note first).

## What the customer does

Routes (session cookie, same-origin and CSRF on every POST; all writes need the customer role):
`GET/POST /api/schedules`, `POST /api/schedules/preview`, `GET /api/schedules/{id}`,
`POST /api/schedules/{id}/preview|replace|cancel|pause|resume`, `GET /api/schedules/substitute-candidates`,
`GET /api/orders` (scheduled, pending, placed, cancelled). Models: `src/aimo/schedule_schemas.py`.

- A schedule is made from a **past order of the same customer**. The server rebuilds the terms (prices
  never come from the client); the customer agrees by sending the `terms_fingerprint` it was shown, a
  price ceiling per run, a recurrence, and per ingredient the accepted substitutes and a percentage
  price range. At most 20 active schedules per customer; it ends 365 days after its first run date.
- Terms never change. Editing or restarting is `replace`: a new authorization that supersedes the old
  one. A stopped schedule keeps its history and shows `replaced_by`.
- Pause skips the dates in the pause (no order, no chat, not a disruption); resume continues from the
  next date; the 365 days keep counting.

## What the worker does

`worker.work_once`: a waiting chat turn first, otherwise one step of one run (`scheduler.run_due_schedules`).
The due-date scan is throttled to `SCHEDULER_PASS_INTERVAL_SECONDS` (30). Runs start from
`SCHEDULER_RUN_AFTER_HOUR` (06, Helsinki) on the scheduled date. One step per iteration keeps the worker
inside its 270 s health limit. A failing scheduler is logged (`scheduler.iteration_failed`) and never stops chat.

`due` -> prepare as the buyer's internal agent, compare with the agreed terms (price within the line's
range, or a usable accepted substitute within range, closest price wins; total within the ceiling;
policy `ready_to_commit`) -> `prepared` -> commit as the **scheduler identity** -> `committed`.
Anything else is a **disruption**: the run is `disrupted`, the schedule `stopped` (reason codes
`PRODUCT_UNAVAILABLE`, `PRICE_OUTSIDE_RANGE`, `CEILING_EXCEEDED`, `RUN_MISSED`, ...), the prepared
request is recorded as cancelled, and a chat starts with a system-authored first message (role `system`)
that tells the agent what is wrong and which lines are still valid ingredients. If the first agent turn
fails, a deterministic message closes it so the customer can still write.
Transient supplier errors retry with backoff (5 attempts), then become a disruption.

## Rules that are easy to break

- The scheduler identity (`scheduler:<md5 buyer>`, role `scheduler`, no login, no model) commits only through
  `scheduler.ensure_commit_allowed`, which re-checks run, authorization, customer and terms under the buyer
  lock. `commit_order` refuses any role without its own branch. Identity rows cannot be created by the
  runtime role: `aimo seed` and the migration create them; a buyer without one fails closed.
- `terms_fingerprint` is not `material_fingerprint`: it leaves out dates, request id, stock, supplier cutoff
  and product facts. The field set is the `TERMS_*` constants in `scheduler.py`.
- A standing order is a free-form basket (a recipe link would attach to the already ordered proposal).
- Accepted substitutes must be inside the buyer's approved product scope (standing product authority).
- Cancelled means an order **request** (append-only `order_request_cancellations`); placed orders stay immutable.
  The unfinished-proposal purge must skip proposals referenced by `scheduled_runs` or the cancellations.

Migration `020_scheduled_orders.sql`; tests `tests/test_schedul*.py`, `test_worker_scheduler.py`,
`test_commit_role_gate.py`, `test_confirm_role.py`. Local runs in fixture mode, not CI.
