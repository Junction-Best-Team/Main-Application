# Person 2: internal purchasing agent

The agent was rebuilt on `develop` `f13b75b`, replacing the earlier runner. Shared
models, product APIs, conversation persistence and purchasing Service remain the
application contracts. No frontend, route, migration or deployment change.

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
`LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOOL_ROUNDS`. No new dependencies or settings;
embeddings stay independent. Missing credentials, configuration errors and invalid
provider responses produce safe errors. Protocol references:
[function calling](https://developers.openai.com/api/docs/guides/function-calling),
[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

## Behavior and controls

The agent clarifies missing delivery/budget/dietary facts and reuses known
constraints. It proposes a recipe basis, total quantities and scaling assumptions
in plan notes for customer review. Carbonara includes pasta, eggs, cured pork,
hard cheese and pepper. Quantities remain recipe estimates; this does not add a
recipe database or deterministic recipe-scaling service.

Canonical Pydantic models validate tool inputs and outputs. Search is not product
verification: every selected ID must be loaded through `get_product`. Every
published ingredient remains required within the turn. Preparation checks exact
ingredient totals/units, aggregating contributions for duplicate SKUs. Service
handles evidence-backed conversion, pack rounding, supplier evidence, scope and
policy. Unknown conversions, shortages and unsupported dietary facts need
resolution; confirmation cannot repair missing facts.

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
retain any verified saved basket or receipt.

Optional callbacks receive immutable `AgentProgress`: turn ID, monotonic sequence,
kind, allowlisted tool name and safe error code. No arguments, tool data, secrets
or model text. Callback failures are logged without contents and cannot hide a
basket. This is a Person 1 integration seam; existing browser SSE still publishes
persisted conversation snapshots. Progress is not a durable execution log.

## Verification

On 2026-11-14, Ruff and 66 deterministic agent/provider tests passed. The full
174-test backend suite passed using dedicated `aimo_person_two_rebuild_test`,
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
exits nonzero. This session had no `LLM_API_KEY`, so no live-provider success is
claimed. Deployment remains an operator task.
