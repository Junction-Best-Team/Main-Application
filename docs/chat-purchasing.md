> Deployment update: [separate apps](separate-apps.md) supersedes this document’s single-container packaging and synchronous turn execution. Product authorization remains unchanged.

# Chat purchasing migration — 2026-11-14

This product scope supersedes the original external-agent/MCP entry points in `brief.md`. One existing React app → authenticated FastAPI → internal typed agent/Service → existing PostgreSQL/supplier connectors. Order placement is a persistent mock, never supplier checkout or stock reservation.

## Integrated product

The root opens chat after sign-in. Conversations have stable URLs and persisted user/assistant messages, proposed recipes and actual proposal links. The customer names the meal and guest count; the agent chooses a suitable saved recipe and server-scales it, searches catalog products, loads their evidence, and prepares the full matched basket through the existing Service. If no suitable saved recipe is available, a labelled assistant-authored recipe estimate is server-scaled instead. The agent chooses ordinary serving sizes and does not ask the customer to calculate ingredient weights. It asks only for material missing facts, including delivery details before preparation, and retains stated dietary needs and hard budgets. Recipe drafts appear in Overview before a proposal exists. Recipe quantities are estimates for customer review. Every ingredient must have an actual product; the prepared request must exactly match the published plan. Unsupported dietary requirements require manual resolution. See [recipe planning](recipes.md) for the separate saved-recipe and draft guarantees.

Purchase history includes existing proposals and accepted mock purchases. The exact old approval URL still loads its stored revision, preserving superseded/rejected/expired/accepted states and an explicit link to current terms. It never silently substitutes new terms.

## Contracts and authorization

`chat_schemas.py` owns MealPlan, AgentTurn, MessageRequest and conversation responses; `schemas.py` retains purchasing contracts. The backend owns routes and generated OpenAPI. The agent owns direct typed Service tools; the frontend consumes generated types. The agent cannot select an authorization identity, edit policy, approve or commit. Its provider credentials remain server-only. Missing provider configuration fails with an actionable error; there is no pretend response fallback.

Privileged migration/seed creates one mapped internal identity per buyer with no authority of any kind (the autonomous limit was removed) and no bearer login. Existing identities remain untouched for references. Existing milk-only demo product scope is preserved: pasta, eggs, pork, cheese and pepper remain outside scope and require the policy's buyer-authorized substitution exception. No wildcard product scope or agent-approved recipe authority is introduced. The buyer can approve only within their current amount and exception limits.

`POST /api/purchases/{id}/confirm` checks browser session/Origin/CSRF, exact proposal/revision, current buyer authority and policy. It persists an immutable confirmation containing the proposal fingerprint and authenticated actor, and records any required approval under the existing buyer lock. Only then does it call existing commit revalidation. Changed price, policy or effective authority produces a new revision without a confirmation; the UI must show new terms and require another explicit click. Denied and needs-resolution baskets remain blocked.

A completed retry returns the persistent identical receipt without contacting provider/supplier. Preparation/commit keys and one-order-per-proposal constraints remain. Internal commit additionally requires an exact persisted confirmation by an active authorized buyer. Legacy approval-only decisions do not satisfy the new internal confirmation gate.

## Persistence and recovery

Conversation creation and messages require stable buyer-scoped keys; changed payloads conflict. A transactional conversation lock reserves one bounded turn, without holding database connections while the model runs. Completed retries replay messages. Failed attempts expose `retry_message` with the original key; crashed work can resume after the 240-second lease. Attempt fencing prevents an old worker publishing a second assistant reply. Preparation keys derive from the trusted turn ID. A stopped process that already prepared a basket recovers that exact proposal before invoking the model again; changed payloads under the same turn key conflict. All decisions and receipts survive process restarts in PostgreSQL.

SSE publishes persisted conversation snapshots and two-second heartbeat comments, with a 25-second reconnect interval and per-poll session revocation checks. It does not stream unpersisted model tokens. Polling remains available on the same detail route. `/mcp` and `/api/agent/*` are absent JSON routes, never SPA fallback.

## Operations

Run `migrate` as setup role for additive migration 003 before the new image; grant runtime access to new tables/sequences and revoke policy/identity provisioning as in `infra/kubernetes/bootstrap.py`. Never reset a production database. Existing policy versions, approvals, orders and audit history remain. `seed` still inserts missing demo data only. Configure the LLM through server-only environment/Secret fields from `.env.example`; local embeddings retain their independent pinned model.

Keep the existing single image/Deployment/Service/database/ingress and allocations. Terraform and portable manifests have been inspected. No infrastructure is applied and no release switch is enabled. The actual selected cluster ingress still needs an operator's streaming smoke after deployment; static rendering/local checks do not establish production routing. Traefik needs no buffering middleware; the app also sets `X-Accel-Buffering: no`. Reused Nginx settings are documented in `deploy/README.md`.

## Verification record

Integrated local validation on 2026-11-14:

- Ruff and backend PostgreSQL/pgvector suite pass, including the full carbonara request → clarification → five actual catalog matches → quantity/commercial/policy validation → authenticated customer confirmation → identical mock receipt retry. The provider and catalog/supplier facts are authored fixtures; no live supplier purchase is claimed.
- Nine Playwright checks pass: seven UI route-fixture regressions plus live-server historical revision and removed-route checks. Generated OpenAPI/TypeScript and production frontend build pass.
- Production multi-stage Docker image builds successfully with the original pinned local embedding model. A dedicated local application container preserves conversation messages, browser session, customer confirmation and identical receipt across an actual container restart.
- Both Terraform stacks format, initialize with existing provider locks, validate and pass all nine mocked plan tests. Sixteen infrastructure helper tests and the Traefik 42.4.0 Helm render pass. No Terraform apply or remote deployment runs.
- Through a disposable local Traefik v3.7.18 proxy (the image selected by the rendered chart), a persisted SSE snapshot and heartbeat arrive in 2.02 seconds, before the 25-second connection closes. Logout revocation is observed on the active stream. This uses a local file-provider route to the same app; the live Kubernetes controller/network/TLS is unverified and still requires the operator smoke after deployment.
- Fixture-mode idle measurement: local application container about 49 MiB and 0.23% CPU; local Traefik about 62 MiB and 0% CPU. These are neither production embedding-model nor load measurements. Resource allocations are unchanged.

No live conversational-provider run was made; configure the server's private LLM key and run the documented demo for that acceptance check. Ordering remains mock.

## When the model provider fails (owner Q-108)

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

## Confirmation line (owner Q-121)

After the customer's confirm route places an order, the chat that holds the basket gets one plain line
(`role` system, `notice` `order_confirmed`): "Order accepted by the demo order service, delivery 17 Nov. This is
a demo order: ..." in Finnish, Swedish or English (the language of the customer's last message, English when
unsure). It is stored with a closed turn keyed by the order, so a replay, a revised or a failed confirm adds
nothing, no model is called and no error text is shown. The model's history leaves it out (the order state
comes from the persisted purchasing state). A scheduled run's own commit writes none. Later fulfilment changes
show on the order card and receipt, not in the chat. Code: `order_notice.py`, `conversations.store_confirmation_line`.

## Bounded parallel reads and interrupted planning

The harness executes independent catalog/product/policy/recipe reads from one model
response in groups of at most four. Each read owns isolated caches; successful results
are applied in model order. Plan changes, matching, supplier lookups, memory changes,
images and basket preparation remain ordered barriers. Cancellation/reclaim fences
cache updates; late reads cannot publish progress or change the live session.

Product search defaults to three candidates and inspects the first three with the
existing catalog reader. These include the same bounded, screened evidence as
`get_product`; the turn reuses those facts and identical searches. Additional results
remain discovery summaries. Inspection never proves recipe suitability, selects a
product, grants purchasing authority or replaces fresh preparation/confirmation checks.

Saved recipe blockers that need reviewed quantities/forms/scaling or suitability/count/
conversion evidence end the turn with the unresolved plan instead of more catalog
searches. Absent/withdrawn products remain searchable. The underlying recipe evidence
requirements are unchanged.

The 90-second turn limit is unchanged. Changed plans are reviewed before display even
without a UI observer. On a later provider failure or timeout, the last approved plan
is saved as a partial answer and the customer can continue with a new message. Later
unreviewed/rejected changes are withheld. If no reviewed progress exists, the ordinary
failed-turn retry remains; timeouts use a specific fixed notice in the customer's
language. Native Google transport timeouts retain `LLM_TIMEOUT` instead of being
reported as generic unavailability.
