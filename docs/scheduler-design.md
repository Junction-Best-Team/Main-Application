# WS-E scheduler: design (no feature code)

Status: design for the owner's review, 2026-11-14. Author: scheduler design session (reports to junction-b5).
Base: `origin/develop` `6ba4754` (worktree `worktrees/p3-scheduler-design`, branch `p3/scheduler-design`). All `file:line` cites are on that commit and were read, not run, unless marked **ran**. Local run, not CI. Every order the scheduler places is a **mock** ("Accepted by demo order service"). No secret was printed or read.

What I ran: the draft migration (below, also `docs/scheduler-migration-draft.sql.txt`) applied on top of migrations 001 to 013 in scratch database `aimo_p3_sched_2_test` (port 55433, container `p3-test-db`) with `psql -1 -v ON_ERROR_STOP=1`, then nine guard checks (terms immutable, one status move only, no delete, one year cap, duplicate (authorization, date) refused, placed order cannot be cancelled, request can be cancelled, cancellation immutable). All nine behaved as intended. Scratch databases `_1_test` and `_2_test` dropped. Nothing else ran: no pytest, no app, no worker.

Requirements read: CNF-001/003/004 (Approved, exception wording added), CNF-022 to CNF-028, CNF-030 to CNF-035 (Approved), CNF-029 Superseded, CNF-026 owner wording. Decisions: review log "Answers on the scheduler" (Q-58 to Q-63), "Owner wording and decisions on the scheduler", "Answers on the scheduler wording" (Q-64, Q-65).

## 0. Summary of what the code forces (read this first)

1. **"Fingerprint equality" cannot be taken literally.** `material_fingerprint` (`purchases.py:285-315`) hashes the whole `request` (including `request_id` and `delivery_date`), each line's `cutoff` (`closingTime`), the full product facts, the policy version and the blocker list. Two runs on different dates never match. The scheduler needs its own **terms fingerprint** over the stable commercial terms (section 3). This is the main design decision in the package.
2. **A new identity role is fail-open in `commit_order` today.** The customer-confirmation gate is `if identity["role"] == "agent" and ...` (`approval_workflow.py:547-571`). Any other role, including a new `scheduler`, skips the gate like an approver does. The gate must become an explicit three-way branch that refuses unknown roles (section 4).
3. **Identity rows cannot be created at runtime.** The runtime database role has INSERT/UPDATE/DELETE revoked on `buyers, identities, policies, internal_agents` (`permissions.py:20-24`) and a trigger blocks updates (`permissions.py:28-51`). The scheduler identity must come from the migration and from seed/provisioning, exactly like the internal agent (`003_chat_purchasing.sql:2-11`, `cli.py:83-91`).
4. **A system-authored first message needs a new stored role.** `conversation_messages.role` is `CHECK(role IN ('user','assistant'))` (`003:31`) and the agent runner rejects any other role (`agent.py:193`). A failed system turn also strands the chat (section 5, trap T1).
5. **The worker health check counts progress only per iteration** (`worker.py:62,66,94-95`, stale after 270 s) and one supplier lookup can take 110 s in the worst case (`upstream.py:64-141`). The pass must do one step of one run per iteration (section 1).
6. **The `orders` table cannot hold "cancelled"** (`008_orders_immutable.sql`, trigger `immutable_orders`). Cancelled applies to an order *request* (a proposal), so it is an append-only table keyed by `proposal_id`, and a placed order can never be cancelled (section 7).

## 1. Where does the scheduler run?

**What exists**
- The worker is one loop: `check_readiness()`, then `run_once(service)` (one chat turn), then `stop.wait(1)` when idle (`worker.py:88-102`). `state["progress"]` is set after each iteration (`:93,95`) and `/health/live` and `/health/ready` return 503 once it is older than 270 s (`:66`). Readiness needs `LLM_API_KEY` and a matching catalog model (`:16-35`).
- Worker pod: restricted runtime DB role, `VALIO_AIMO_API_KEY` and `LLM_API_KEY` in secret `aimo-worker-runtime` (`infra/kubernetes/main.tf:79-95`, `deploy/kubernetes.yaml:143-148`). So the worker already has everything a run needs (database, supplier lookups). `strategy = Recreate`, `replicas = var.app_replicas` (`main.tf:124`, replicas from `var.app_replicas`), so several replicas must be safe.
- Catalog sync is a CronJob and says it "never runs inside the API or worker processes" (`catalog_sync.tf:1-3`), because it is heavy (3 GiB limit, `deploy/catalog-sync-cronjob.yaml`). It needs a Terraform apply to exist. The release workflow does not apply Terraform (`docs/release-migrations.md`; the cluster check found the infra supplier-mode default still `fixture` for that reason: `evidence/e2e/cluster.md` item 1).
- Advisory lock keys in use: 893017 (`ingest.py:42,691`), 893018 (`cli.py:21`), 893019 (`ingest.py:44`, `recipe_import.py:110`; two meanings share it), 893020 (`recipes.py:184`). Next free: **893021**.

**What is missing:** any code that creates or executes a scheduled run.

**Design (agrees with the coordinator's recommendation, with two refinements)**
- Logic lives in one module, `src/aimo/scheduler.py`, entry point `run_due_schedules(service, *, now=None, today=None) -> bool` (returns whether it did work, like `run_once`). The worker loop calls it after `run_once` returns False. A later CronJob `aimo run-schedules` can call the same function (no new image, but it would need a Terraform apply, so not now).
- **Refinement 1, advisory lock only where it is useful.** Step 1 (materialise due runs) takes `pg_advisory_xact_lock(893021)` in a short transaction. Step 2 (execute) does not need a session lock: runs are claimed with `FOR UPDATE SKIP LOCKED` and a lease, the same pattern as `claim_turn` (`conversations.py:199-235`, lease 240 s at `:234`). The unique key `(authorization_id, scheduled_date)` makes materialising idempotent even without the lock; the lock only avoids replicas doing the same scan.
- **Refinement 2, one step per iteration.** A run is a small state machine, `due -> prepared -> committed` (or `needs_customer` / `disrupted`). One iteration performs exactly one step for one run. Worst case per step is about 110 s (two sequential POSTs, each up to 3 attempts of 15 s plus at most 5 s waits: `upstream.py:64,118,129`, so about 55 s each), and a basket larger than one lookup batch needs more POSTs (`upstream.py:149-151`; unverified for large baskets). Prepare plus commit in one iteration could pass 220 s and would sit close to the 270 s limit. Two steps per run keeps each iteration well under it. The materialise step is one indexed query and runs at most every 30 s.
- Failure of the pass must not stop chat: wrap the pass in its own try/except inside the loop, log `scheduler.iteration_failed` with the safe `failure(exc)` helper (`worker.py:100`), and do not flip `state["ready"]`.
- **Coupling to accept:** a worker replica that fails readiness (no LLM key, catalog mismatch) does not run schedules, although the commit path needs no LLM (CNF-013). Acceptable for the MVP; with two replicas the other one still runs.
- Time: "today" is `now().astimezone(upstream.HELSINKI).date()` (`upstream.py:21`). Runs execute from `SCHEDULER_RUN_AFTER_HOUR` (new setting, default proposed 06, Helsinki) on the scheduled date. New settings go in `config.py` with defaults, so no infra change is needed.
- Catch-up: a run is created only for `next_run_date <= today`. A date older than `today` when first seen (downtime) is created as `disrupted` with `RUN_MISSED`, which stops the schedule (CNF-030) and starts the chat. Open question O-7.

## 2. Data model

Full migration text: `docs/scheduler-migration-draft.sql.txt` (**ran** on 001 to 013, clean). Filename `0NN_scheduled_orders.sql` with the next free number on develop at the time it is written (013 is the highest today: `migrations/` listing; the runner sorts by full filename, `migrations/README.md`). Add its row to the allocation table in `migrations/README.md`.

| Table | Purpose | Mutability |
|---|---|---|
| `scheduler_identities` + identity rows `scheduler:<md5(buyer)>` with a new role value `scheduler` | one non-login, no-authority identity per buyer, like `internal_agents` | provisioning only (runtime role cannot write `identities`) |
| `scheduled_authorizations` | the customer's standing terms: source order, stored request (lines, destination, flags; no dates), `agreed_lines` (per-line unit net/gross, tax rate, sales quantity), `terms_fingerprint`, `price_ceiling_gross`, `delivery_offset_days`, `recurrence`, `first_run_date`, `valid_until` (at most `first_run_date + 365`, DB check), `status`, `next_run_date`, `supersedes_id`, `create_key`/`create_hash` (idempotent create, as `conversations.create`, `conversations.py:36-48`) | **terms immutable** (trigger raises on any change to a terms column or on delete); `status`, `stop_reason`, `next_run_date`, `updated_at` move; once the status leaves `active` the row never changes again |
| `scheduled_runs` | one row per authorization per scheduled date; `UNIQUE (authorization_id, scheduled_date)` is the CNF-025 key; `proposal_id`, `order_id`, `conversation_id` each `UNIQUE`; `status` due, prepared, committed, needs_customer, disrupted; `attempts`, `lease_until`, `reason_code`, `reason` (structured differences) | mutable state machine |
| `scheduled_run_events` | append-only log of every step with actor (scheduler identity) and detail | immutable (`immutable_record()` from `001:72-73`) |
| `order_request_cancellations` | "cancelled" for an order request, `proposal_id` primary key, reason `run_disrupted`, `run_retry`, `customer_revised`, `customer_cancelled`; a trigger refuses a proposal that already has an order | immutable |
| `conversation_messages.role` check widened to include `system` | the system-authored first message | n/a |

Answer to "immutable-record rules for runs?": the **authorization terms and the event log and the cancellations are immutable; the run row is a mutable state machine**, because it must move through steps, and every move is also written to the append-only event log. This matches the repo pattern (mutable `proposals`/`approvals`, immutable `proposal_revisions`/`audit_events`/`orders`: `001:72-76`, `008`).

Edit rule: terms never change, so "edit" and "restart" both create a **new** authorization that `supersedes_id` the old one (old becomes `superseded` or stays `stopped`). This also resets the agreed prices, which is what CNF-032 needs after the customer agrees to a new price (O-3).

Cap (CNF-026): `valid_until` is fixed at creation, at most 365 days after `first_run_date`; the materialise step sets `status='expired'` when `valid_until < today`. Interpretation to confirm: a stop and a later restart do **not** extend the year, because the restart is a new authorization with its own year, and the old one expires on its original date (O-6).

New buyers: the migration inserts a scheduler identity for every buyer that exists when it runs (like `003:5-11`). A buyer created later has none until provisioning adds it. `seed()` must add the demo buyer's (`cli.py:83-91` is the model). A buyer without one fails closed: the run becomes `disrupted` with `SCHEDULER_NOT_CONFIGURED` (as `auth.internal_agent` raises `AGENT_NOT_CONFIGURED`, `auth.py:29-31`). **Ran:** my scratch check inserted a buyer after the migration and got zero scheduler identities, which confirms the gap.

## 3. How a run builds a proposal and compares it with the agreed terms

**Creating the authorization from a past order (CNF-031, CNF-022, CNF-032)**
1. Source: an `orders` row of the same buyer. The reorder request is `proposal_revisions.request` at `orders.revision` (`001:44-50,58-62`), with `delivery_date` and `request_id` removed, and `recipe_plan_id` / `recipe_plan_revision` dropped. Dropping is required: a recipe-backed prepare reuses the *same* proposal id and appends a revision (`approval_workflow.py:262-269`), which would attach to the already ordered proposal, and `PurchaseRequest` forbids contributions together with a recipe plan (`schemas.py:146-147`). Consequence: a standing order is always a **free-form basket**; recipe completeness guarantees do not carry over (R-4).
2. `POST /api/schedules/preview` builds a snapshot with `purchases.build_snapshot(identity, request, connector)` (`purchases.py:87`), which persists nothing, and evaluates policy with `evaluate_purchase` (as `commit_order` does, `approval_workflow.py:518-523`). It returns the lines with unit net/gross, the gross total, the outcome and a `terms_fingerprint`. Preview is not a purchase and does not appear in the orders list.
3. `POST /api/schedules` repeats the build server-side and refuses with `SCHEDULE_TERMS_CHANGED` (409) when the fresh `terms_fingerprint` differs from the `agreed_terms_fingerprint` the customer saw. The server never trusts prices from the client. It also refuses unless the outcome is `ready_to_commit` (a basket that needs approval or substitution would pause every run, CNF-024) and `price_ceiling_gross >= gross total`. The customer's authenticated, CSRF-checked call is the exact-terms agreement (CNF-022; role must be `approver` like `record_human_decision`, `approval_workflow.py:365-366`).

**Terms fingerprint** (new function `terms_fingerprint(request, snapshot)` next to `material_fingerprint`): hash of destination, currency, and per line `product_id`, the quantity (`sales_quantity`, `sales_unit`), `deposit_lines` (material, quantity, unit), the unit `net`, `gross`, `tax_rate` from `commercial_evidence`, and whether the product is deleted. It deliberately excludes `request_id`, `delivery_date`, `observed_at`, `closingTime`, stock level, the policy version and the full product facts. Reasons: they change every run or are checked on their own. Policy and blockers are tested separately (below). Facts are excluded because a new catalog generation can reword a product without changing what is bought, which would pause every schedule (risk R-3; strictness is O-4). The existing `material_fingerprint` is untouched, so stored fingerprints stay valid.

**What one run does (steps in section 1)**
- Step A, `due`: re-read the authorization under `FOR SHARE`; refuse when it is not `active`, past `valid_until`, or its creator is no longer an active approver (`conversations.py:258-262` uses the same test for turns). Prepare through `Service.prepare_order` as the buyer's **internal agent** (`auth.internal_agent`, `auth.py:20-32`), with `idempotency_key = sched-<run id>-<attempt>` and `request_id = standing-<auth>-<date>`. Reason for the internal agent: proposals belong to an agent (`proposals.agent_id`, `approval_workflow.py:34`), and the human confirm route commits through the proposal's agent (`conversations.py:459-465`); if the scheduler identity prepared, a price-pause proposal could not be confirmed by the customer without changing both places. The audit shows `scheduled_run_prepared` by the scheduler identity in `scheduled_run_events`. The key must change per attempt: a repeated key returns the *old* proposal even after expiry (`prior_preparation`, `approval_workflow.py:220-232`; README "use a new key for a fresh proposal after expiry"). The superseded attempt's proposal is cancelled with reason `run_retry`.
- Compare the new revision with the authorization (pure function `compare(auth, proposal) -> Verdict`, unit-testable with no database):
  1. `policy_outcome == ready_to_commit` and no `denied` or `unresolved` reasons on any line (this covers unavailable stock, cutoff passed, supplier block, deleted product: `purchases.py:127-188`, `upstream.py:421-470`). Otherwise **disrupted**.
  2. Same line set and same quantities (`sales_quantity`). A line gone, added or re-converted is **disrupted**.
  3. Per-line unit price against `agreed_lines`, and the terms fingerprint. Only prices differ, everything else equal: **needs_customer** (`PRICE_CHANGED`, CNF-032, Q-64). The reason lists each line `{product_id, agreed_gross, current_gross}` and the total difference.
  4. `gross_total <= price_ceiling_gross`. Over the ceiling is a price pause too (`CEILING_EXCEEDED`), and the customer must raise the ceiling (O-3).
  5. All equal: status `prepared`.
- Step B, `prepared`: `Service.commit_order(scheduler_identity, CommitRequest(proposal_id, revision, idempotency_key = sched-commit-<run id>))`. The commit path already re-fetches supplier evidence, revalidates under the buyer lock, appends a new revision when terms moved, and returns the saved receipt for a repeated key (`approval_workflow.py:483-617`). Handling: receipt means `committed` with `order_id`; `{"status": "revised", ...}` (`:540-543`) means the terms moved between prepare and commit, so re-run the comparison on the new revision (price-only becomes `needs_customer`, otherwise `disrupted`); `PROPOSAL_EXPIRED` returns the run to `due` with attempt + 1; `COMMIT_BLOCKED`, `APPROVAL_REQUIRED`, `AUTHORITY_REVOKED` and other Problems become `disrupted` with the Problem code in `reason`. Transient supplier codes (`UPSTREAM_UNAVAILABLE`, `UPSTREAM_RATE_LIMITED`, `DATABASE_BUSY`) retry with backoff for at most 5 attempts, then `disrupted` (O-8).
- One order per authorization per date holds in four independent layers: the run unique key, `scheduled_runs.proposal_id` unique, `orders.proposal_id` unique (`001:59`), and the commit idempotency key (`approval_workflow.py:601-609`). A repeated pass for the same date reads the existing run and returns its result (CNF-025).

## 4. Scheduler identity and what it may call

**What exists:** two roles in the identities check (`001:12`). `context()` accepts any active identity whose role matches the row (`purchases.py:41`). `proposal()` restricts only `role == "agent"` to its own proposals (`approval_workflow.py:34`). The only commit gate is for agents (`:547-571`): an agent needs a `customer_confirmations` row for the exact revision and fingerprint from an approver who can approve the amount. An approver commits without it, because the confirmation is that approver's own click (`conversations.py:436-458`). Login and sessions accept only `role='approver'` (`auth.py:97-101,120-127`), and the model runner accepts only `role='agent'` (`agent.py:179-185`), so a `scheduler` row can neither log in nor run a model.

**Design**
- Role value `scheduler` (check widened, migration), credential `!scheduler-no-login`, authority `{}`.
- Rewrite the gate as an explicit dispatch that fails closed:
  ```
  role = identity["role"]
  if role == "agent":      customer-confirmation check (unchanged)
  elif role == "scheduler": scheduler.ensure_commit_allowed(c, identity, p, r, snapshot, evaluated)
  elif role != "approver":  raise Problem("FORBIDDEN", ..., 403)
  ```
- `ensure_commit_allowed` runs inside the commit transaction, after the buyer lock and the fresh snapshot, and requires **all** of: a `scheduled_runs` row with this `proposal_id`, the same `buyer_id`, status `prepared`; its authorization `active` and not past `valid_until` (Helsinki date); the authorization's creator still an active approver of that buyer; the stored request equal to the proposal's request apart from the run's dates and id; the fresh `terms_fingerprint` equal to the authorized one; every line price equal to `agreed_lines`; `gross_total <= price_ceiling_gross`; `evaluated["policy_outcome"] == "ready_to_commit"`. Any miss raises `SCHEDULE_NOT_AUTHORIZED` (403). Because it uses the fresh snapshot, it holds at commit time, not only at prepare time. `approval_required` can never pass: the scheduler is not an approver, so `authorize_commit` also refuses it (`approval_workflow.py:462-480`).
- `proposal()` for role `scheduler` returns only proposals linked in `scheduled_runs` of that buyer. This closes "never use another buyer's authorization" at the read too (the buyer scope is already `AND buyer_id=%s`, `:31`).
- **May call** (the scheduler module is the only holder of this identity): `workflow.commit_order` (gated), `workflow.get_proposal` / `get_order` (scoped), reads of its own authorization and run rows, and writes to run state and the event log. **May not**: create, cancel, edit or restart an authorization (customer functions require `role == "approver"` and raise `FORBIDDEN` otherwise), prepare an order itself, log in, run the model, record a decision or a customer confirmation, touch policy or memory. The engine's own state changes to an authorization (stop on disruption, expire at `valid_until`) are private functions that take no identity and can only move `active` to `stopped` or `expired`; the database trigger forbids any change to terms.
- **Honest limit:** the runtime database role has write rights on every table except the four provisioning ones (`permissions.py:10-24`). The boundary is therefore enforced in code and by the triggers, not by database grants, the same as for the agent today. A grant-level boundary would need a separate database role; out of scope.
- `tests/test_agent_cannot_purchase.py` and `tests/test_tool_surface.py` must stay green: the scheduler adds no agent tool and no purchase verb.

## 5. How a disrupted run starts the chat

**What exists:** `conversations.create` (buyer lock, idempotent on `(buyer_id, create_key)`, `conversations.py:27-49`), `enqueue` (a turn row plus the user message, `:107-165`), `claim_turn`, `execute_turn` (`:238-348`). `execute_turn` needs `requested_by` to be an active approver of the buyer (`:258-264`); it builds the model history from stored messages with their roles (`:278-280`) and the runner rejects roles other than user and assistant (`agent.py:193`). `submitted_by` NULL means memory is unavailable for that turn (`:269-276`). The agent's tools have no purchase verb (`agent_tools.py:276`; `test_agent_cannot_purchase.py`).

**Design**
- In one transaction, idempotent: `INSERT conversations` with `create_key = sched-run-<run id>` (unique per buyer, `003`), `INSERT conversation_turns` (key `sched-run-<run id>`, state `queued`, `requested_by` = the authorization's creator, `submitted_by` NULL), and `INSERT conversation_messages(role='system', text=...)`, then set `scheduled_runs.conversation_id` (unique). The existing worker claims the turn as an ordinary agent turn. If the creator is inactive, use the first active approver of the buyer; if there is none, the run stays `disrupted` without a chat and an event says so.
- Storage role `system` (migration), exposed as `ChatMessage.role = "system"` (`chat_schemas.py:57`; person 1 regenerates `schema.ts`, interface change, O-9). When `execute_turn` builds the provider history, a `system` message is sent as a `user` message prefixed with "Standing-order notice written by the system, not typed by the customer" so `validate_context` and the guardrail input screening (`guardrails.py:686-744`, which key on `user`) keep working and the catalog names in it are screened like other untrusted text.
- **What the message carries** (structured block plus one sentence, all values from the run's `reason` JSON): the scheduled and delivery dates; the reason codes; per line the product id, name, quantity, the agreed unit gross price, the current unit gross price, and a status `available_same_price` (a "confirmed product"), `price_changed`, `unavailable` (with available quantity), `withdrawn`, `blocked_by_policy`; the total difference; the previous proposal id if one was prepared. Instruction to the agent: treat every `available_same_price` line as a valid ingredient and keep it; for each problem line find alternatives (`list_substitution_candidates`, `Service.list_substitution_candidates`, `service.py:99`), explain the price differences, and ask which replacement the customer wants; then `prepare_order` for the customer to confirm in the product (the normal workflow; chat text never buys). This is CNF-028 and CNF-033: the customer adds replacements only for the problem lines.
- A price-only pause (CNF-032) uses the same mechanism; the proposal of that run is already prepared and the customer can confirm it with the normal confirm route, so the chat only explains the differences.
- **Trap T1 (must be designed in):** if a system turn fails (provider error, three worker attempts: `conversations.py:221-229`), `enqueue` refuses new messages with `RETRY_PREVIOUS_MESSAGE` (`:124-131`) and `detail()` builds `retry_message` from a joined *user* message (`:82-87`), which a system turn does not have. The customer would be stuck. Fix in `conversations.py` (person 1's file; the owner allows edits): when a system turn reaches `failed`, write a deterministic assistant message from the run's `reason` JSON ("The standing order could not be placed. Here is what changed: ...") and mark the turn `complete`. Test first (section 9, T-16).
- The conversation title: "Standing order, <date>: needs your attention". `disrupted` also cancels the run's prepared proposal (section 7).

## 6. Routes (customer, session cookie plus CSRF like `api.py:195-223`)

Person 1 owns UI; the owner allows person 3 to add Service functions and routes. UI template: PR #102 `ui/desktop/schedule_page_left_sidebar_nav`, `edit_schedule_left_sidebar_nav_variant` (read: card per schedule with cadence, next drop, lines, price; edit page with cadence presets weekly, twice weekly, every 4 days, bi-weekly, custom). Not in our data: unload window, hub, waybill, SKU manifest edits (O-10).

| Route | Purpose | Requirement |
|---|---|---|
| `GET /api/schedules` | list with status, next run date, last run status, link to chat | CNF-034 input |
| `GET /api/schedules/{id}` | terms, agreed prices, ceiling, runs, chat id | |
| `POST /api/schedules/preview` `{order_id, recurrence, first_run_date}` | no write; terms and fingerprint | CNF-031 |
| `POST /api/schedules` `{order_id, recurrence, first_run_date, price_ceiling_gross, agreed_terms_fingerprint, idempotency_key}` | create | CNF-022, 031, 032 |
| `POST /api/schedules/{id}/cancel` | stop all later runs | CNF-027 |
| `POST /api/schedules/{id}/replace` `{recurrence?, price_ceiling_gross?, agreed_terms_fingerprint, idempotency_key}` | edit or restart: new authorization superseding the old one | CNF-030 restart, UI "Save changes" |
| `GET /api/orders?offset&limit` | orders list with status (section 7) | CNF-034 |

Problem codes (same `{"error": {"code","message"}}` shape): `SCHEDULE_TERMS_CHANGED` 409, `SCHEDULE_NOT_REORDERABLE` 422 (order of another buyer is `NOT_FOUND` 404 as `owned()`), `SCHEDULE_CEILING_TOO_LOW` 422, `SCHEDULE_NOT_ACTIVE` 409, `SCHEDULE_LIMIT` 429 (at most 20 active per buyer, proposed), `SCHEDULE_NOT_AUTHORIZED` 403 (engine only), `SCHEDULER_NOT_CONFIGURED` 503. All write routes require role `approver`. Regenerate `frontend/openapi.json` and the types (README: `uv run python scripts/export_schema.py && npm run types --prefix frontend`); that frontend file edit is person 1's line (README notes the generated types are theirs), so a PR from us should include only the Python side and say so.

## 7. Orders list: scheduled (with date), pending, cancelled

**What exists:** `GET /api/purchases` lists *proposals* by `updated_at` (`conversations.py:362-372`), each rendered with `approval_status` and `order_status` (`approval_workflow.py:93-212`, `order_status` is `accepted_mock` or `not_placed`). `orders` is immutable (`008`). There is no cancelled concept anywhere, and no orders route (ws-d gap G3).

**Design:** the list is derived, with one new append-only table. Row kinds, newest first, one query (a UNION with a buyer filter and paging):
- **scheduled (date):** one per `active` authorization, date = `next_run_date`; a virtual row, not an order. Also a run in `needs_customer` shows as `pending`.
- **pending:** a proposal with no order, no cancellation, current revision not expired (`proposal_revisions.expires_at`), i.e. "being processed and placed". Includes proposals prepared by the agent in chat and the run proposals waiting for a price agreement.
- **cancelled:** a proposal with a row in `order_request_cancellations`. Written when (a) a run is disrupted and its proposal is dropped (`run_disrupted`), (b) the customer revises it (`customer_revised`), (c) a retry replaced it (`run_retry`, hidden from the list), (d) the customer cancels (`customer_cancelled`). Owner wording: "in the case of the order requiring some changes, it becomes canceled and a new order would be placed" (CNF-035). Recommended timing: cancel the original request **when the run is disrupted**, and let the revised basket appear as a new `pending` row. The alternative (cancel when the replacement is confirmed) leaves the original `pending` forever if the customer abandons the chat; the owner decides (O-1).
- A cancelled proposal must refuse commit: add `ensure_not_cancelled(c, pid)` next to `meals.ensure_active` (`approval_workflow.py:508`) and a status `cancelled` in `render()` (`approval_status` is a plain `str`, `schemas.py:249`, so no type break; `CommitResponse.approval_status` is a Literal and is unaffected).
- **Not in the owner's list:** orders that were *placed* (and expired proposals). I recommend a fourth status `placed` (mock "Accepted by demo order service", with the receipt link) and hiding expired un-confirmed proposals from the list; the owner decides (O-2).
- Orders are never updated or deleted, so CNF-020 and the `immutable_orders` trigger stay as they are.

## 8. Risks

- R-1 **Fail-open role gate** (finding 2). Mitigated by the explicit dispatch and the first red test.
- R-2 **Stuck chat after a failed system turn** (T1). Mitigated by the deterministic fallback message.
- R-3 **False pauses.** The terms fingerprint includes unit prices to the cent. The fixture prices are invented and the live price endpoint has validity windows (`upstream.py:395-410` `PRICE_OUTSIDE_VALIDITY`), so real price changes at a period boundary will pause schedules by design. Facts are left out of the fingerprint on purpose (O-4).
- R-4 **Recipe-backed orders lose their recipe link** when reordered (section 3).
- R-5 **Supplier cutoff.** Each product has a `closingTime` (`upstream.py:442-445`); a run at the configured hour can find `CUTOFF_PASSED` for products with early cutoffs, which would stop the schedule. Real cutoff times are unverified; the run hour and the lead time (`delivery_offset_days`) are O-5.
- R-6 **Live traffic.** Every run is two lookups (prepare, then commit revalidation) for the shortlist only. 20 schedules per buyer on the same morning is a burst against an undisclosed rate limit (`upstream.py:149-151`). Mitigation: one run per iteration plus the 30 s materialise interval spreads them; a per-pass cap is easy to add.
- R-7 **Code-level, not grant-level, boundary** for the scheduler (section 4).
- R-8 **Worker redeploys.** `strategy = Recreate` (`main.tf:124`) stops the worker during a rollout; runs are leased and dated, so a run resumes after, but a date that passes during a long outage becomes `RUN_MISSED` (O-7).
- R-9 **Migration order.** The new code reads the new tables, so (like 009/010 in ws-d section 4) the migration Job must run before the new worker image. `/health/ready` has no schema probe for new tables (`api.py:136`, `worker.py:29`); add one `to_regclass('scheduled_runs')` probe to `check_readiness` so a stale schema fails loudly.
- R-10 **Edits conflict with "approve exact terms once".** The UI template lets the customer change lines and quantities of a schedule. Terms are immutable here, so any edit is a replacement with a fresh agreement; line editing is not planned (new quantities mean a new past order).
- R-11 **Clock and time zone.** All date logic uses `Europe/Helsinki`; a test must cover a Helsinki date that differs from the UTC date.

## 9. Test plan (written first, red before green; none of these exist yet, none has been run)

Style: the existing hermetic suite (`tests/conftest.py`: `service`, `connector` = `FixtureClient` with `price_multiplier` and `stock` knobs, `buyer`, `agent` fixtures; `TRUNCATE buyers ... CASCADE` reset covers the new tables because they reference `buyers`). Engine functions take `now`/`today` so no sleeping. One file per area, one commit per requirement. DB-name rule: scratch `aimo_p3_sched_<n>_test` on port 55433, one suite at a time.

Write these first, in this order (each is red today for the reason given):

| # | Test | Requirement | Red today because |
|---|---|---|---|
| T-1 | `commit_order` with an identity of role `scheduler` and no run/authorization raises `SCHEDULE_NOT_AUTHORIZED` (and an unknown role raises `FORBIDDEN`) | CNF-023, CNF-001 | role `scheduler` violates the identities check; once added, today's gate lets it commit (R-1) |
| T-2 | scheduler cannot commit another buyer's proposal, nor a proposal that belongs to no run | CNF-023 (Q-60) | no gate |
| T-3 | `schedules.create` / `cancel` / `replace` with a `scheduler` or `agent` identity raise `FORBIDDEN`; with the buyer they succeed | CNF-022, CNF-023 | no module |
| T-4 | create from a past order of the same buyer works; an order of another buyer is `NOT_FOUND`; a basket needing approval is `SCHEDULE_NOT_REORDERABLE`; stale `agreed_terms_fingerprint` is `SCHEDULE_TERMS_CHANGED`; the same key twice returns one row; same key, other body is `IDEMPOTENCY_CONFLICT` | CNF-022, CNF-031 | no module |
| T-5 | `terms_fingerprint`: equal for two prepares on different dates and request ids at the same prices; differs when one price, one quantity or one product changes | CNF-024, CNF-032 | function missing (pure test, no DB) |
| T-6 | `next_dates(recurrence, from)` for weekly, twice weekly, every N days, bi-weekly; never past `valid_until`; Helsinki date differs from UTC date | CNF-026 | function missing |
| T-7 | `valid_until` over 365 days is refused by the API and by the DB check; pass at `valid_until` marks `expired` and creates no run | CNF-026 | no table |
| T-8 | happy path: one pass creates the run, a second pass commits it; receipt label "Accepted by demo order service"; audit actor is the scheduler identity; **no LLM call** (provider disabled as in `test_confirmation_contract.py`) | CNF-001 exception, CNF-013, CNF-018 | no engine |
| T-9 | repeated passes and two concurrent passes (threads, as `test_worker.py`) for the same date give one run, one proposal, one order, the same result | CNF-025 | no engine |
| T-10 | price up by 10 % (`price_multiplier = 1.1`): nothing committed, run `needs_customer` with per-line agreed/current prices, schedule still `active`, a chat exists | CNF-024, CNF-032, Q-64 | no engine |
| T-11 | price pause left open when the next date arrives: run `disrupted` (`price_not_agreed`), schedule `stopped`, no new run | Q-64, CNF-030 | no engine |
| T-12 | product out of stock (`connector.stock`), withdrawn product, `denied` or `needs_resolution` outcome: nothing committed, schedule `stopped`, proposal cancelled, chat started | CNF-024, CNF-030 | no engine |
| T-13 | cancelled or expired or superseded authorization, creator deactivated: nothing committed; a cancelled schedule creates no later run | CNF-024, CNF-027 | no engine |
| T-14 | supplier down (`UPSTREAM_UNAVAILABLE`): retried up to the limit, then `disrupted`; no duplicate order after recovery | CNF-025, Q-62 | no engine |
| T-15 | a run whose proposal changes between prepare and commit (price moved in between) returns `revised` and ends `needs_customer`, never `committed` | CNF-024 | no engine |
| T-16 | disrupted run: conversation exists with the `system` first message holding reasons, problem lines and the available confirmed lines; running the turn with a fake runner stores the assistant reply; **a failed system turn leaves a deterministic assistant message and the customer can send a new message** (T1) | CNF-028, CNF-033 | role `system` rejected by the check; no code |
| T-17 | the same run never starts two chats (repeat the pass) | CNF-025 | no engine |
| T-18 | orders list: `scheduled` with `next_run_date`, `pending`, `cancelled`; cancelling a proposal does not touch `orders`; a placed order cannot be cancelled (DB trigger and Python); `UPDATE`/`DELETE` on cancellations and run events are refused | CNF-034, CNF-035, CNF-020 | no table |
| T-19 | a cancelled proposal cannot be confirmed or committed | CNF-035 | no guard |
| T-20 | agent tool surface unchanged: no scheduler or purchase tool (`test_tool_surface.py`, `test_agent_cannot_purchase.py` stay green) | CNF-003 | regression guard |
| T-21 | HTTP: each route needs the session cookie, the Origin and the CSRF token; another buyer's schedule is `NOT_FOUND`; OpenAPI lists the routes | CNF-022, 027 | no routes |
| T-22 | migration: applies on 001 to 013, is additive on a populated database, creates one scheduler identity per existing buyer, the row guards (nine checks I ran) hold; `test_additive_migrations.py` and `test_migrations.py` pass | | no migration |
| T-23 | worker: `run_due_schedules` is called from the loop only when no chat turn was claimed; one step per call; a raising pass does not make the worker unready | health, section 1 | no code |

Each requirement gets an evidence file as the work package asks (method, command, pass/fail condition, result); the scheduler-specific live check is a fixture-mode drive of the whole flow through `TestClient` as in `evidence/e2e/ws-d.md`, with the worker pass called in-process.

## 10. Open questions for the owner (each with my recommendation)

- **O-1 Cancelled timing.** When is the original request marked cancelled: when the run is disrupted (recommended) or when the replacement order is confirmed?
- **O-2 Status list.** Add `placed` (recommended) and hide expired proposals? The owner's list has only scheduled, pending, cancelled.
- **O-3 Agreeing a new price.** After a price pause, how does the customer agree so the schedule continues at the new price? Recommended: a `replace` call (new authorization with the new agreed prices and, if the new total is above the ceiling, a new ceiling set by the customer) plus the normal confirm of that run's proposal. If the customer confirms the order but never replaces, the next run pauses again on the same price difference.
- **O-4 What counts as "the same terms".** Recommended: product ids, quantities, deposits, unit net/gross/tax rate, destination, currency; product facts excluded. Stricter (facts included) means more pauses after catalog updates.
- **O-5 Run hour and lead time.** Recommended: run at 06:00 Helsinki, `delivery_offset_days` copied from the past order (delivery date minus order date, at least 1). Supplier cutoffs are unverified.
- **O-6 One-year cap.** Recommended: fixed 365 days from the first run date; a restart is a new authorization with its own year. The alternative counts only running days.
- **O-7 Missed dates.** Recommended: a date older than today when first seen becomes `disrupted` (`RUN_MISSED`), stops the schedule and starts the chat, instead of silently ordering for a past date.
- **O-8 Transient supplier failure.** Recommended: 5 attempts with backoff inside the same date, then `disrupted` (Q-62 says "skips this run and reports it"; CNF-030 says a disrupted order stops the schedule).
- **O-9 Interface changes for person 1.** `ChatMessage.role` gains `system`; `approval_status` may be `cancelled`; new routes and schemas. OK to edit their files and regenerate types?
- **O-10 UI fields we do not have** (unload window, hub, SKU manifest editing, "pause" button). Recommended: not in scope; `cancel` and `replace` only.
- **O-11 Active schedule limit** per buyer (proposed 20) and a per-pass run cap.
- **O-12 Chat for a price-only pause.** Recommended yes (the owner wants the customer notified; no other notification exists).
- **O-13 Requirement wording check.** CNF-003 says a purchase confirmation comes from a human, with the exception for the scheduler; the implementation commits through `commit_order` with a gate, not through the human confirmation route. If the owner wants a literal `customer_confirmations` row per run, that would record a human who did not click, which I advise against.

## 11. Work order after approval

1. Migration and identity, `terms_fingerprint`, `next_dates` and the pure `compare` with tests T-5, T-6, T-7, T-22.
2. Gate rewrite and `ensure_commit_allowed` (T-1, T-2, T-3); `schedules` Service functions (T-4).
3. Engine: materialise, claim, steps A and B, pause rules, worker hook (T-8 to T-15, T-23).
4. Chat start and the failed-turn fallback (T-16, T-17).
5. Cancellations and the orders list (T-18, T-19).
6. Routes and schema export (T-21), evidence files, `migrations/README.md` row, `docs/` short page, findings.
