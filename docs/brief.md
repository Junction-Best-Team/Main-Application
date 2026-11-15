# Aimo product brief

The product is a React customer chat app, an authenticated FastAPI API and a
durable worker, backed by PostgreSQL/pgvector. It helps a buyer turn a meal and
guest count into a checked basket and a **persistent mock order**. The supplier
has no order-placement or reservation endpoint. Receipts say **“Accepted by demo
order service”** and explicitly state that no supplier order or reservation exists.

This is the current purchasing contract. See [chat behavior](chat-purchasing.md),
[architecture](architecture.md) and [README](../README.md) for the implementation,
setup and demo commands. Earlier implementation plans remain in Git history.

## Customer flow

1. Sign in and describe a meal, guest count and any dietary needs or hard budget.
2. The assistant selects a saved recipe or a labelled assistant estimate. The
   server scales quantities; catalog evidence establishes actual product matches.
   Unsupported requirements and incomplete saved recipes need resolution.
3. The server prepares a basket with current supplier price/availability, quantity
   calculations, delivery terms and purchasing checks. The customer can review
   and [edit the cart](cart-purchase.md).
4. The customer explicitly confirms the exact proposal revision. The API records
   the authenticated confirmation and revalidates before saving a mock receipt.
   Changed terms require review and another explicit confirmation.

Chat text, a model-generated approval, a URL and viewing a proposal cannot confirm
an order. The internal agent can search, plan and prepare; it cannot approve,
commit, select its identity or edit its own authority. `/mcp` and `/api/agent/*`
are retired. Historical approval URLs retain their exact stored revisions;
`/approvals` redirects to purchase history.

[Standing orders](scheduler.md) use separately persisted, customer-approved terms.
The scheduler's restricted commit gate rechecks each run against that authorization,
current policy and commercial evidence; it cannot use the chat agent's permissions.

## Catalog and commercial evidence

- Import verified complete catalog snapshots explicitly or through the configured
  [catalog-sync Job](catalog-sync.md). Publish atomically; a failed import leaves
  the active catalog usable. Preserve withdrawal markers and purchase snapshots.
- Search the static catalog first, then query live supplier price and availability
  only for shortlisted products. Never poll the supplier for the entire catalog.
- Keep product IDs, raw units, source/version and known, derived, unknown or
  conflicting evidence. Similarity and model scores do not establish suitability.
- Product/query embeddings must match the active model/profile. Changing profiles
  requires a coordinated [index cutover](google-models.md).
- Application pricing requires the private `VALIO_AIMO_API_KEY` and uses the live
  supplier. Missing credentials fail startup/readiness; authored supplier responses
  are confined to the test harness. Historical fixture evidence stays labelled.

## Quantities and hard checks

Use exact fractions for supported quantity conversions and decimal money. Preserve
sales units, source lot steps, requested amounts, rounding and excess. Whole discrete
sales units are an explicit buyer policy, not a rewrite of the source lot step.
Do not infer food content from gross packaging weight, convert mass to volume
without evidence, or treat a product name as verified structured packaging data.

A complete gross payable total includes product price, tax, deposits and applicable
charges. Missing prices or deposit costs are unresolved, never zero. Demo delivery
charges are zero by adapter definition; real checkout needs an upstream contract.

Check supported dietary requirements against positive and conflicting evidence;
lactose-free does not establish milk-free. Check price validity, currency, sales
blocks, stock units/quantity, delivery date and Helsinki cutoff. Unknown supplier
quantity, variable weight, ambiguous conversions, conflicting dietary claims and
passed cutoffs cannot be repaired by a spending approval.

## Buyer policy and authority

Policy is versioned in PostgreSQL. Seed inserts missing demo configuration without
overwriting existing settings. The optional account-wide `max_order_gross`, each
human approver's amount/currency/exception permissions and the request's hard budget
all apply. Agents hold no spending authority; historical `autonomous_limit` and
`spend` fields are ignored.

Product and delivery scopes are provisioned server-side. Missing product scope
blocks purchasing. Products outside `approved_product_ids` count as substitutions
even when the agent omits `substitutes_for`. Substitution and overbuy rules are
`allowed`, `requires_approval` or `forbidden`; mandatory requirements still apply.
The demo product scope is `464306` and destination is `hotel-helsinki`.

Signed-in active human buyers can change the account cap, substitution/overbuy rules
and whole-sales-unit setting through [Settings](policy-settings.md). This preserves
hidden product/delivery scopes and personal approval authority. Saves require the
expected policy version, retain history and invalidate stale confirmations.

The deterministic evaluator returns these outcomes in precedence order:

| Outcome | Meaning |
| --- | --- |
| `denied` | A known prohibition or hard request/account limit fails. Approval cannot override it. |
| `needs_resolution` | Required facts, scope or authority are missing/conflicting, or no active approver covers the total and every required exception. |
| `approval_required` | Hard checks pass and a permitted substitution/overbuy exception needs an eligible buyer's decision. |
| `ready_to_commit` | Hard checks pass without an outstanding policy exception. Customer confirmation is still required for chat purchases. |

Keep policy outcome, approval state and order status distinct. Semantic
[guardrails](guardrails.md) supplement these deterministic controls; they never
supply purchase authority. Saved [memory](memory.md) cannot grant it either.

## Persistence, isolation and retries

Bind buyers and actors to authenticated server-side identities. Authorize every
read/write by buyer; browser writes require session, exact Origin and session-bound
CSRF. Keep credentials out of source, browser bundles and logs.

Persist proposal revisions, policy/evidence snapshots, approvals, exact authenticated
confirmations, orders, receipts and ordinary audit events. Approval binds the buyer,
products, quantities, destination/date, currency, total, expiry and policy version.
Recheck current human authority and commercial evidence before each new commitment.
Material changes create a new revision and invalidate prior confirmation/approval.

Preparation keys are stable across retries and scoped to buyer plus agent; changed
payloads conflict. Completed authorized commit retries return the stored receipt
before any supplier call. Unique constraints enforce one order per proposal and one
payload per buyer-scoped commit key. Fetch supplier evidence outside the short
transaction; lock buyer, identities and proposal consistently for the final check
and atomic order write. Privileged policy/authority updates take the same buyer lock.

Conversations, retries and queued jobs survive restarts. Attempt fencing prevents
stale workers from publishing or preparing twice. Preserve historical transactions;
never reset a database to perform an upgrade. Deployment/migration procedures live
in [infrastructure](../infra/README.md) and [release migrations](release-migrations.md).

Keep [preparation and third-party provenance](pre-existing-work.md) for submission.
Record new verification in PR descriptions, rather than an append-only findings log.
