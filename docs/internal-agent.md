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

The current UI renders ingredient names/amounts and plan notes; it does not show
a per-row unresolved status. The agent now supplies an explicit unresolved list
in persisted final text. Person 1 must add the row state and persist any required
schema additions with the server recipe/context changes. Tests needed at that
boundary: omitted eggs/pork on first and later turns cannot prepare; implausible
per-portion totals fail; model assumptions cannot relax a persisted budget/diet.

Final text always labels plan quantities as estimates independently of the model.
This label does not satisfy the missing domain acceptance checks above.
