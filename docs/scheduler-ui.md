# Scheduler UI (standing orders)

Frontend for the standing-order (scheduler) backend: a customer turns a past order into a recurring one, sees what happened on each run, and can pause, resume, cancel, edit or restart it. Every order the scheduler places is a mock order ("Accepted by demo order service"). The backend contract is documented in [standing orders](scheduler.md). Browser tests use mocked API routes; they do not establish live backend behavior.

## Screens and routes

| Route                                        | Page                                     | What it shows                                                                                                                                                                                                                                      |
| -------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/schedules`                                 | `features/schedules/pages/SchedulesPage` | Cards for the customer's standing orders: title, status chip, cadence, next run, agreed total, lines, last run. Pause or resume from the card. A stopped one shows why and links to its chat. A stopped schedule that has `replaced_by` is hidden. |
| `/schedules/:scheduleId`                     | `ScheduleDetailPage`                     | Terms, price ceiling, agreed lines with accepted substitutes and price range, run history (newest first), and the actions Pause, Resume, Edit, Cancel (inline confirmation) and Restart.                                                           |
| `/schedules/new?order=<order_id>`            | `ScheduleCreatePage`                     | Create from a placed order: recurrence, first run date, per-ingredient substitutes and price range, preview, price ceiling, an explicit authorization statement, create.                                                                           |
| `/schedules/:scheduleId/edit` (`?restart=1`) | `ScheduleEditPage`                       | Replace (edit) or restart. Lines are read-only. A restart picks the confirmed revised order from the customer's placed orders.                                                                                                                     |
| `/purchases`                                 | `purchases/pages/PurchasesPage`          | The orders list from `GET /api/orders`: scheduled, pending (with Cancel request), placed ("Schedule this order") and cancelled rows.                                                                                                               |
| `/`                                          | `home/pages/HomePage`                    | A real "Standing orders" card and recent placed orders.                                                                                                                                                                                            |
| Chat                                         | `chat/components/SystemMessage`          | A `system` message (first message of a disrupted run's chat) renders as a neutral banner "Valio Aimo system".                                                                                                                                      |

## API used (generated types in `src/shared/api/schema.ts`)

`GET /api/schedules`, `GET /api/schedules/{id}`, `POST /api/schedules/preview`, `POST /api/schedules`, `POST /api/schedules/{id}/preview`, `/replace`, `/cancel`, `/pause`, `/resume`, `GET /api/schedules/substitute-candidates`, `GET /api/orders` (with `status`, `total`, `placed_at`), `POST /api/purchases/{id}/cancel`, `GET /api/purchases/{id}` and `/receipt`. Every write sends `X-CSRF-Token`; create and replace send a client-generated `idempotency_key` (the same key on a retry of one attempt, a new key when an input changes).

## States and statuses

Schedule status chips are derived in `features/schedules/model/scheduleStatus.ts`: Scheduled (`active`), Paused, Stopped needs attention (`stopped`), Cancelled, Expired, Replaced (`superseded`). Run statuses: `due`, `prepared`, `committed` (Order placed), `disrupted` (needs attention), `skipped` (paused date: no order, no chat). Eleven stop reasons have one plain sentence each (`STOP_REASON_TEXT`). Every page has loading, empty, error and 401 states (401 signs the customer out through `useAuth`).

## Error codes handled

`ApiError` (`src/shared/api/client.ts`) keeps `status`, `code` and `details` and reads both `{error:{code,message,details?}}` and FastAPI's `{detail:[...]}`. Codes with their own behaviour: `SCHEDULE_TERMS_CHANGED` (clear the terms and re-preview once), `SCHEDULE_CEILING_TOO_LOW` (field error), `SCHEDULE_NOT_REORDERABLE` (blocking reasons, create disabled), `SCHEDULE_NOT_ACTIVE` (reload), `SCHEDULE_LIMIT` (20 active), `IDEMPOTENCY_CONFLICT` (new key), `INVALID_FIRST_RUN_DATE` / `INVALID_RECURRENCE` / `INVALID_LINE_RULE`, `ORDER_ALREADY_PLACED` and `NOT_FOUND` on cancelling a request, `FORBIDDEN`.

## Left out on purpose (owner decisions)

Unload window, delivery hub / dock / lockbox, editing products or quantities of a schedule, shipment tracking and waybills, lot substitution approval, skip / duplicate / approve-all, temperature classes, a modification cut-off. A change of products is a new order (restart or replace).

## What the specs mock

Playwright specs intercept `/api/**` with `page.route` and use typed fixtures made up for the tests (`e2e/support/schedulerFixtures.ts`, `proposalFixture.ts`, `scheduleEditorMock.ts`); the shapes come from the generated schema, the values are invented. They prove behaviour against authored responses, not the live backend, supplier or provider. Specs: `schedules.spec.ts`, `schedule-create.spec.ts`, `schedule-edit.spec.ts`, `orders.spec.ts`, `home-schedules.spec.ts`, `system-message.spec.ts`, `schedule-nav.spec.ts`, and the updated `chat.spec.ts`.
