# Person 2: internal purchasing agent

The agent was rebuilt on `develop` `f13b75b`, replacing the earlier runner. Shared
models, product APIs, conversation persistence and purchasing Service remain the
application contracts. This PR changes the agent only; the runtime/configuration
work is split into PR #32 for Person 1 review. No deployment is performed.

## Entry point

`aimo.agent.run_turn(identity, messages, service, *, on_progress=None,
budget_seconds=90) -> AgentTurn` is synchronous. Person 1 owns worker execution,
persistence, turn serialization, recovery and browser events. Supply an active
server-scoped agent with `id`, `buyer_id` and persisted `_turn_id`, and persisted
user/assistant text. Oversized history fails explicitly without silently dropping
earlier customer constraints.

- `agent.py`: instructions, bounded provider/tool loop, progress and final result.
- `agent_provider.py`: OpenAI-compatible function calling, validated wire
  responses, context/response limits and transient retries.
- `agent_tools.py`: typed direct Service tools and verified plan/basket
  associations. Person 3 owns deterministic domain arithmetic and authorization.

Use existing server settings `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`,
`LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOOL_ROUNDS`, `LLM_REASONING_EFFORT` and
`LLM_MAX_COMPLETION_TOKENS`. The main model defaults to Sonnet 5.5 through
OpenRouter; [operational logging](logging.md) describes compatibility, overrides
and diagnostic events. Embeddings stay independent. Missing credentials, configuration errors and invalid
provider responses produce safe errors. Protocol references:
[function calling](https://developers.openai.com/api/docs/guides/function-calling),
[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

## Behavior and controls

Semantic guardrails (TypeSafe Jev, enforced by default; shadow/off available) wrap the runner at
four boundaries; deterministic controls below remain authoritative. See
[guardrails](guardrails.md).


The agent reuses known constraints, chooses ordinary serving sizes and asks only
for facts it cannot derive (normally guest count and delivery details). It does not
ask the customer for ingredient weights or calculations. Budget may remain unset;
stated hard limits and dietary needs remain enforced. It proposes a recipe basis,
total quantities and scaling assumptions
in plan notes for customer review. Carbonara includes pasta, eggs, cured pork,
hard cheese and pepper. Quantities are recipe estimates for customer review. For
saved recipes the server scales them (`scale_recipe`, exact fractions, rounded up to
four decimals), so the model does no arithmetic; see [recipes](recipes.md).
When no suitable saved recipe is available, `draft_recipe` accepts a complete
assistant-authored base recipe and server-scales it to the guest count. Drafts are
labelled estimates, retain the free-form completeness warning and appear in
Overview before preparation. They cannot replace a selected unresolved saved plan.

Canonical Pydantic models validate tool inputs and outputs. Search is not product
verification: every selected ID must be loaded through `get_product`. Every
published ingredient remains required within the turn. Preparation checks exact
ingredient totals/units, aggregating contributions for duplicate SKUs. Service
handles evidence-backed conversion, pack rounding, supplier evidence, scope and
policy. Unknown conversions, shortages and unsupported dietary facts need
resolution; confirmation cannot repair missing facts.

Limits and error details (what the model and the browser see):

- The ingredient and basket-line limits are `MAX_BASKET_LINES` (`schemas.py`) and the
  recipe/meal-plan limits in `recipe_schemas.py` and `recipes.py`; the owner's decision
  (Q-67) is 100 everywhere, applied by the cap change tracked separately. A plan or recipe
  over the limit is refused with a code that names the limit and the count.
- `match_ingredients` matches several ingredients in one call: one plan revision,
  all-or-nothing; one product not read with `get_product` refuses the whole batch. A
  refused product is kept on its ingredient as `rejected`.
- A basket that does not equal the plan returns `MEAL_BASKET_MISMATCH`; the same product
  in two units is combined into the priority unit (kg, then L) when catalog evidence
  allows, otherwise `UNIT_CONVERSION_UNKNOWN`. Both errors carry `error.details` with the
  required lines (`required`, `missing`, `unexpected`, `wrong_amount_or_unit`), so the
  model is told exactly what to send.
- Every HTTP error is `{"error": {"code", "message", "details"?}}`, including validation
  errors (code `VALIDATION_ERROR`, `details` = `type`/`loc`/`msg`, never the submitted
  input), unknown routes and wrong methods; it is declared in the OpenAPI document.
- A free-form basket line lists the plan ingredients it combines (`contributions`); a
  saved-recipe line takes them from the saved plan. A line short of stock carries
  `quantity.shortfall`, the missing sales units.
- A hosted deployment (`SECURE_COOKIES=true`) with `UPSTREAM_MODE` `live` or `auto` and no
  `VALIO_AIMO_API_KEY` does not start (API startup and the worker readiness check).

There is no model approval, confirmation, policy editing or commit operation.
Typing “approved” cannot buy. Preparation keys use `chat-` plus the persisted turn
fingerprint, matching backend recovery. After successful preparation, that turn's
plan and commercial request are fixed; identical retries remain valid. Recipe or
terms changes require a new customer turn. Other purchase reads cannot replace
the prepared basket association. Later status comes from saved proposals/receipts.
Orders remain mocks, without supplier checkout or inventory reservation.

The cooperative time budget defaults to 90 seconds (caller may choose up to 120),
with configured provider timeouts/round limit, at most 12 calls per response and
four cumulative tool errors. Grouped tools execute serially. Provider completions
have at most one transient retry and never retry early with `Retry-After`.
Supplier/database tools retain their own timeouts; a running synchronous tool
cannot be interrupted by this runner. Empty/invalid/provider-failed final replies
retain any verified saved basket or receipt. Unexpected provider/Service errors
also emit safe error progress and preserve that result; tools are not automatically
retried after an unexpected failure. Remote provider URLs require HTTPS; HTTP is
allowed only for localhost or loopback IP development.

Optional callbacks receive immutable `AgentProgress`: turn ID, monotonic sequence,
kind, allowlisted tool name and safe error code. No arguments, tool data, secrets
or model text. Callback failures are logged without contents and cannot hide a
basket. This is a Person 1 integration seam; existing browser SSE still publishes
persisted conversation snapshots. Progress is not a durable execution log.

## Verification

After review on 2026-11-14, Ruff and 79 deterministic agent/provider tests passed.
The full 188-test backend suite passed using dedicated `aimo_person_two_rebuild_test`,
including provider HTTP parsing → runner → real purchasing functions →
authenticated customer confirmation → saved mock receipt. Provider HTTP responses,
catalog, embeddings and supplier facts are authored fixtures. One existing
Starlette/httpx deprecation warning; no live supplier check or deployment.

Run the bounded real-provider protocol check when configured:

```sh
uv run python scripts/smoke_agent_provider.py --require-config
```

It makes at most two completions (each with one possible transient retry), using
one authored read-only policy result, without a database/supplier/purchase call.
The default command prints `skipped` without credentials; `--require-config`
exits nonzero. The initial rebuild had no configured key and skipped this check.

The owner subsequently selected OpenRouter. Private local configuration uses
`https://openrouter.ai/api/v1` and `openai/gpt-4.1-mini`. The private key is stored
in the ignored local `.env` (mode 0600) and repository secret `LLM_API_KEY`;
`LLM_BASE_URL` and `LLM_MODEL` are repository variables. The live smoke then
**passed two completions** with an authored read-only policy result. This verifies
provider authentication and a tool round trip, not a live supplier purchase.

The separate [runtime PR #32](https://github.com/Junction-Best-Team/Main-Application/pull/32)
proposes loading these settings during an authorized release, with no patch or
same-image restart for unchanged values. No deployment, release activation or
cluster Secret mutation ran in this session.

## Review handoff and acceptance gaps

[PR #19](https://github.com/Junction-Best-Team/Main-Application/pull/19) is the
canonical Person 2 agent PR; #12 and #16 are superseded. The
[owner review](https://github.com/Junction-Best-Team/Main-Application/pull/19#issuecomment-6877724578)
keeps model scaling temporarily. These are merge dependencies, not completed
acceptance checks:

| Requirement | Current behavior and remaining work | Owner |
| --- | --- | --- |
| MEA-003 / MEA-004 | Deterministic scaling and prevention of double scaling are **not met**. The model supplies totals; exact basket equality verifies copying, not arithmetic. Keep these checks open until deterministic scaling exists. Add per-portion sanity bounds now under the review's temporary decision. | Person 3 |
| MEA-007 / MEA-008 | The agent refuses listed ingredients without a product and reports their names in its final text. It cannot detect an ingredient omitted from the first plan or a later turn. A server carbonara template must define required ingredients and refuse preparation while any remain unresolved. | Person 3; Person 2 consumes the result |
| MEA-010 / POL-008 | Prompt instructions preserve constraints but provide no trusted provenance or hard-constraint guarantee. Derive and persist trusted constraints server-side; tag model additions as assumptions and prevent them loosening user/reviewed requirements. | Person 1 context/persistence; Person 3 enforcement; Person 2 runner integration |

Person 1 retains sole ownership of `chat_schemas.py` and must agree the context
contract before a `run_turn` signature change. Proposed contract for that review:
a server-only keyword context containing constraint kind/value, source
(`user_request` or `reviewed_plan`) and persisted evidence reference (message ID or
authenticated plan revision). Extraction and evidence validation happen outside
the model; model tool arguments cannot assign those sources. Model additions are
separate assumptions. Missing or conflicting trusted facts must request resolution,
not silently use a model value. This contract is proposed, not implemented.

**Built (POL-008, backend half):** `run_turn(..., constraints=None)` and `ToolSession(..., constraints=None)`
take a server-only list of `{name, value, source, confirmed}` (`name` is `budget_gross`, `lactose_free`,
`milk_free` or `unsupported:<text>`). No tool input accepts it (extra arguments are rejected with
`INVALID_TOOL_ARGUMENTS`). `Service.prepare_order(..., constraints=)` stores it in the revision's
request JSON under `constraints` (key omitted when empty; no new table), so the fingerprint covers it,
and refresh and commit re-evaluate with the stored record; callers never see the key. Entries with
source `stated_assumption` and `confirmed` false are ignored; trusted values set the stricter limit.
A looser request value or a dropped flag adds `CONSTRAINT_LOOSENED` (unresolved, so `needs_resolution`),
and a looser budget is enforced at the customer's number (`HARD_BUDGET_EXCEEDED`, denied). The model fills
nothing in the record: the customer does (owner Q-97), see below.

**Producer (owner Q-97).** `POST /api/conversations/{id}/messages` takes an optional `constraints`
object, `{budget_gross, lactose_free, milk_free}`; only the signed-in customer can send it. The
server stores it as records `{name, value, source: "user_request", confirmed: true}` in the turn's
`constraints` column (migration 021, additive, never in a field the UI shows as content), covers it
in the turn's idempotency hash (the same key with another record is `IDEMPOTENCY_CONFLICT`), and the
worker hands the limits in force to `run_turn(constraints=)`, which reaches `prepare_order`
through `ToolSession`. The limits in force are the latest value per name over the conversation's
turns up to this one; a toggle sent as `false` withdraws that requirement. Without any limit the
runner is called exactly as before. The reply's `retry_message` carries the fields back so the
client can retry the unfinished message with the same key. The UI must add the fields later.
Scheduled runs (`scheduled_request`) are the scheduler's change: see
`evidence/ws-c/scheduler-constraints-patch.md`.

**Limits (MEA-013, owner Q-67: "raise the limit to 100, not 1000, and apply this everywhere").** A
meal plan, a saved recipe, a purchase request and a `match_ingredients` batch hold at most 100
ingredients or lines (`MAX_BASKET_LINES`); `scale_recipe` refuses a larger recipe
(`RECIPE_TOO_LARGE`). The supplier lookup keeps the supplier's own limit of 1000 product ids per
request (`MAX_LOOKUP_IDS`, `MAX_MATERIALS`); larger lookups are split into batches (SUP-007). The
guardrail limits were raised with the cap (`MAX_STATE_BYTES` 28,000 to 120,000, `MAX_NARRATIVE_CHARS`
12,000 to 30,000). Measured offline with realistic Finnish product names: the output-review state
is 27,944 bytes at 30 lines and 86,772 bytes at 100 lines (683 bytes per proposal line), the
displayed plan 16,917 characters, and the check that gates preparation only 16,535 bytes (below
TypeSafe's long-context threshold of about 32,000 bytes). The classifier's latency above that
threshold is not measured (no key here); a timeout fails closed (reply replaced, plan withheld,
proposal and link kept).

The current UI renders ingredient names/amounts and plan notes; it does not show
a per-row unresolved status. The agent now supplies an explicit unresolved list
in persisted final text. Person 1 must add the row state and persist any required
schema additions with the server recipe/context changes. Tests needed at that
boundary: omitted eggs/pork on first and later turns cannot prepare; implausible
per-portion totals fail; model assumptions cannot relax a persisted budget/diet.

Final text always labels plan quantities as estimates independently of the model.
This label does not satisfy the missing domain acceptance checks above.
