# Chat purchasing

The [product brief](brief.md) defines the purchasing controls. The React app calls authenticated FastAPI; a durable worker runs the internal typed agent/Service against PostgreSQL and supplier connectors. Order placement is a persistent mock, never supplier checkout or stock reservation.

## Integrated product

The root opens chat after sign-in. Conversations have stable URLs and persisted user/assistant messages, proposed recipes and actual proposal links. The customer names the meal and guest count; the agent chooses a suitable saved recipe and server-scales it, searches catalog products, loads their evidence, and prepares the full matched basket through the existing Service. If no suitable saved recipe is available, a labelled assistant-authored recipe estimate is server-scaled instead. The agent chooses ordinary serving sizes and does not ask the customer to calculate ingredient weights. It asks only for material missing recipe facts and retains stated dietary needs and hard budgets. Delivery settings are reviewed in Your order, without asking for dates or locations in chat. Replies focus on the current request, normally in one or two sentences; they do not append a recipe/delivery/checkout checklist. Background preparation updates the order card silently on success, with a brief chat notice for blocked baskets or omitted ingredients. Detailed purchasing reasons stay in Your order. Recipe drafts appear in Overview before a proposal exists. Recipe quantities are estimates for customer review. Every ingredient must have an actual product; the prepared request must exactly match the published plan. Unsupported dietary requirements require manual resolution. See [recipe planning](recipes.md) for the separate saved-recipe and draft guarantees.

Purchase history includes existing proposals and accepted mock purchases. The exact old approval URL still loads its stored revision, preserving superseded/rejected/expired/accepted states and an explicit link to current terms. It never silently substitutes new terms.

## Conversational request understanding

The customer may start with an undecided idea, a named dish, their own recipe or a
product list. `record_request` retains the goal, starting point, portions, recipe
reference, budget, requirements, material missing facts and labelled assumptions.
It is conversation-scoped working state, separate from long-term memory and
purchase authority. Migration `026_request_brief.sql` adds the per-turn snapshot.
Writes are fenced to the running attempt and authenticated message author; semantic
review must preserve earlier facts and requirements unless the customer changed them.
Under enforcement, a fresh reviewed understanding is required for preparation.

Exploration can use discovery tools without selecting a meal or changing the cart.
Once the meal/products and required quantities are clear, the assistant builds the
list, retaining all requirements in both tool-driven and background preparation.
Customer recipes use their supplied base quantities and server scaling, with added
estimates identified separately. `resize_plan` recalculates portions, including a new
saved plan for a locked recipe basket; `revise_recipe` supports explicit ingredient
changes as a reviewed estimate and keeps unchanged product matches. Old proposals
and receipts remain historical. Equivalent SKU changes still require product evidence.

The cart owns SKU, pack and price details. Chat contains the conversation and compact
recipe entry, without a second set of SKU cards. Failed background
preparation keeps the draft and explains that basket checking could not finish.

Optional [supplier metric preferences](supplier-metrics.md) can guide comparisons:
historical delivery reliability and estimated product-group carbon footprint. Product
tools return both metrics; one explicit saved preference applies to later searches.
These are optional conversation choices, never a mandatory questionnaire or checkout rule.

## Contracts and authorization

`chat_schemas.py` owns MealPlan, AgentTurn, MessageRequest and conversation responses; `schemas.py` retains purchasing contracts. The backend owns routes and generated OpenAPI. The agent owns direct typed Service tools; the frontend consumes generated types. The agent cannot select an authorization identity, edit policy, approve or commit. Its provider credentials remain server-only. Missing provider configuration fails with an actionable error; there is no pretend response fallback.

Privileged migration/seed creates one mapped internal identity per buyer with no authority of any kind (the autonomous limit was removed) and no bearer login. Existing identities remain untouched for references. Existing milk-only demo product scope is preserved: pasta, eggs, pork, cheese and pepper remain outside scope and require the policy's buyer-authorized substitution exception. No wildcard product scope or agent-approved recipe authority is introduced. The buyer can approve only within their current amount and exception limits.

`POST /api/purchases/{id}/confirm` checks browser session/Origin/CSRF, exact proposal/revision, current buyer authority and policy. It persists an immutable confirmation containing the proposal fingerprint and authenticated actor, and records any required approval under the existing buyer lock. Only then does it call existing commit revalidation. Changed price, policy or effective authority produces a new revision without a confirmation; the UI must show new terms and require another explicit click. Denied and needs-resolution baskets remain blocked.

A completed retry returns the persistent identical receipt without contacting provider/supplier. Preparation/commit keys and one-order-per-proposal constraints remain. Internal commit additionally requires an exact persisted confirmation by an active authorized buyer. Legacy approval-only decisions do not satisfy the new internal confirmation gate.

## Persistence and recovery

Conversation creation and messages require stable buyer-scoped keys; changed payloads conflict. A transactional conversation lock reserves one bounded turn, without holding database connections while the model runs. Completed retries replay messages. Failed attempts expose `retry_message` with the original key; crashed work can resume after the 420-second lease. Attempt fencing prevents an old worker publishing a second assistant reply. Preparation keys derive from the trusted turn ID. A stopped process that already prepared a basket recovers that exact proposal before invoking the model again; changed payloads under the same turn key conflict. All decisions and receipts survive process restarts in PostgreSQL.

SSE publishes persisted conversation snapshots and two-second heartbeat comments, with a 25-second reconnect interval and per-poll session revocation checks. It does not stream unpersisted model tokens. Polling remains available on the same detail route. `/mcp` and `/api/agent/*` are absent JSON routes, never SPA fallback.

## Operations

Apply migrations and runtime grants through the [release migration procedure](release-migrations.md)
or the local setup in [README](../README.md). Never reset an existing database.
Policy versions, approvals, orders and audit history remain; `seed` inserts missing demo data only.
Configure server-only provider settings from `.env.example`.

The frontend, API and worker run as [separate apps](separate-apps.md).
The [deployment runbook](../deploy/README.md) covers routing and SSE checks;
static rendering and local tests do not establish production routing.
SSE needs unbuffered proxy responses; the API also sets `X-Accel-Buffering: no`.

## When the model provider fails

A turn that fails because the model provider fails (any `LLM_*` error of the provider layer) stores
one plain assistant message and keeps the retry offer. The text is fixed and deterministic (no model
call, no error detail) and follows the language of the customer's last message, English when unsure:
"I could not reach the assistant just now. Please try again." / "En saanut yhteyttä avustajaan
juuri nyt. Yritä uudelleen." / "Jag kunde inte nå assistenten just nu. Försök igen." The message
carries `notice: "provider_unavailable"` (column `conversation_messages.notice`, migration 024), so
the browser shows it as a notice and the model's history leaves it out. It occupies the turn's single
assistant slot: a retry of the same message (same key) removes it, a repeated failure writes one again,
and the real reply replaces it when the retry succeeds, so there is never more than one per turn.
Guardrail, policy and programming errors store no notice. The unfinished message still appears as
`retry_message`; a new message is refused until it is retried (`RETRY_PREVIOUS_MESSAGE`).

## Confirmation line

After the customer's confirm route places an order, the chat that holds the basket gets one plain line
(`role` system, `notice` `order_confirmed`): "Order accepted by the demo order service, delivery 17 Nov. This is
a demo order: ..." in Finnish, Swedish or English (the language of the customer's last message, English when
unsure). It is stored with a closed turn keyed by the order, so a replay, a revised or a failed confirm adds
nothing, no model is called and no error text is shown. The model's history leaves it out (the order state
comes from the persisted purchasing state). A scheduled run's own commit writes none. Later fulfilment changes
show on the order card and receipt, not in the chat. Code: `order_notice.py`, `conversations.store_confirmation_line`.

## Bounded parallel reads and interrupted planning

The harness executes independent catalog/product/policy/recipe reads from one model
response in groups of at most four. A response may contain up to 100 calls, with at
most 12 calls outside that read-only allowlist; a turn may execute up to 256 calls
within its existing deadline. Oversized batches are rejected whole before execution.
Each read owns isolated caches; successful results
are applied in model order. Plan changes, matching, supplier lookups, memory changes,
images and basket preparation remain ordered barriers. Cancellation/reclaim fences
cache updates; late reads cannot publish progress or change the live session.
Provider diagnostics record finish reasons, call counts and fixed validation categories,
never response text or tool arguments. A reviewed partial response displays as paused,
stops the local message queue, and offers to draft a continuation for unmatched
ingredients. Sending it resumes the saved plan through the ordinary authenticated chat.

Product search defaults to three candidates and inspects the first three with the
existing catalog reader. These include the same bounded, screened evidence as
`get_product`; the turn reuses those facts and identical searches. Additional results
remain discovery summaries. Inspection never proves recipe suitability, selects a
product, grants purchasing authority or replaces fresh preparation/confirmation checks.

Product searches share the overall 256-call turn budget, configured model-round
limit (40 by default and at most) and 360-second maximum deadline. There is no separate
product-search cap. Catalog reads still run at most four at a time; identical
searches reuse existing results and ordinary repeated-call discipline still applies.
A terminal completion carrying an error is persisted as an interruption for the existing
paused/continue UI; private error details stay server-side. This does not rewrite
the activity of older completed turns.

Recipe details expose missing quantities/forms and unsupported scaling/units before
saved-plan selection. Incomplete candidates use a complete alternative or labelled
assistant estimate; scaling refuses to persist them as a newly selected saved plan.
Existing saved plans retain their unresolved ingredients while matching can continue
for other items. The assistant explains the specific gaps and avoids repeated
searches for facts catalog discovery cannot resolve. The underlying saved-recipe
evidence requirements are unchanged.

Changed plans are reviewed before display even
without a UI observer. On a later provider failure or timeout, the last approved plan
is saved as a partial answer and the customer can continue with a new message. Later
unreviewed/rejected changes are withheld. If no reviewed progress exists, the ordinary
failed-turn retry remains; timeouts use a specific fixed notice in the customer's
language. Native Google transport timeouts retain `LLM_TIMEOUT` instead of being
reported as generic unavailability.
