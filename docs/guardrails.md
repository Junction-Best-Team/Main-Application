# Agent guardrails

The chat agent has two layers of protection. **Deterministic controls** are the
authority and run in every mode. **Semantic checks** (Gemini Decision 1) add a
probabilistic opinion at five boundaries. A model "allow" never grants permission,
skips validation or replaces the customer's confirmation.

Code: `src/aimo/guardrails.py` (policy `guard-2026-11-14.4`), wired in
`agent.py`, `agent_tools.py` and `conversations.py`.

## What is deterministic

| Boundary | Control |
| --- | --- |
| User → LLM | Session cookie, exact Origin and CSRF on writes, buyer-scoped conversations; 4,000-character messages; one unfinished turn per conversation; **new:** at most 3 queued/running turns and 60 new messages per hour per buyer (HTTP 429; constants in `conversations.py`). The model only ever sees user/assistant roles; identity comes from the server. |
| LLM → tool | Typed purchasing and recipe tools plus two memory tools, no approve/confirm/commit/policy tool; memory writes act for the persisted turn's human, are fenced to the current attempt and need an expected revision ([memory](memory.md)); `extra="forbid"` arguments (identity, authority or retry keys are rejected); products must be loaded with `get_product`; the basket must equal the published plan; server-generated idempotency key; Service enforces buyer scope, policy, commercial evidence and state transitions. |
| Tool → LLM | **New:** tool results are reduced to what the assistant needs. Proposals lose buyer/agent IDs, audit history and raw evidence; price lookups lose raw supplier payloads (normalised values, mode and timestamps stay); free text is length-bounded. External records are wrapped in `{"result": …, "data_handling": …}` and the prompt says that text is data. The saved purchase history added to each new turn uses the same projection **without product names**, because it is not screened in that turn; `get_proposal` returns screened names when needed. |
| LLM → user | Proposal links and status notices come from saved, buyer-scoped records (`ToolSession.result`); a runner-supplied proposal ID is re-read as the buyer before it is linked. Plain-text rendering in React (no raw HTML). |
| Confirmation | `POST /api/purchases/{id}/confirm`: session, Origin, CSRF, buyer ownership, exact revision, current authority/policy, persisted confirmation, idempotency key and one order per proposal. Unchanged by this work; regression tests in `test_guardrails_integration.py`. |

## What is semantic

Gemini Decision 1 is called through Google's native `/v1beta/decisions` endpoint
with `noul` questions. Screened text goes only into serialized `input`; question
instructions and true/false criteria are server constants. No fallback to another
provider occurs. The retained Jev adapter requires explicit
`GUARDRAIL_PROVIDER=openrouter` selection and its separate credential.

| Boundary | When | Questions | Enforcement |
| --- | --- | --- | --- |
| User → LLM | Once per turn: latest customer message plus up to four earlier customer messages (multi-turn attacks) | `manipulation` (override rules, impersonation, secrets, chat purchasing authority, steering the classifier); `in_scope` | Blocked → server reply, no model call. Out of scope → short redirect. Uncertain → the turn runs but cannot prepare a basket. Unavailable → turn fails with `GUARDRAIL_UNAVAILABLE` (retryable). |
| Tool → LLM | Catalog text in search/product/proposal results, batched once per model reply and cached by exact text | Does the text contain instructions aimed at an assistant/reviewer? | Flagged or unchecked text is withheld from the model, and that product cannot be prepared. |
| LLM → tool | Before a new `prepare_order` only, after the deterministic checks. The current text of every selected product is screened first, because one reply can fetch new descriptions and prepare before that reply's tool results are screened | Destination/date, budget, lactose/milk-free requirements and items match what the **customer** said (assistant text and the model's meal plan are labelled as not evidence); the displayed basket label (`request_id`) is neutral | Blocked/uncertain/unavailable → no preparation; the model is told to ask the customer. Same arguments reuse the verdict, so retrying cannot fish for an allow. |
| LLM → tool (memory) | Before each `manage_memory` write. State: the persisted customer messages, the immediately preceding assistant reply (marked model-authored), the proposed change and, for update/delete, the current item. No catalog, supplier or recipe text | `persistence_intent` (the latest customer message asks to keep, change or forget it for the future), `matches_request`, `scope` (shared vs personal is clear), `no_authority` (no credentials, payment data or purchasing authority) | Any failure, uncertainty, unavailability or an unpassed input screen → no write; the assistant is told to ask the customer. |
| LLM → user | Everything the model wrote for display, the reply **and** the meal plan (title, ingredient names, notes), against trusted records (proposal, receipt, tool outcomes, product and commercial evidence). Text is never clipped into review: oversized output counts as uncertain | Unsupported purchase status, prices/stock, dietary safety, disclosure | The reply is replaced by a server-authored fallback and the plan is withheld. The proposal, its link and the trusted status notice are kept. Under enforcement a plan is also withheld when the turn ends before review (provider failure, step or error limit). |

Read-only tools other than catalog text are not sent to the classifier. A typical turn makes
2 calls (input and output); a basket turn adds about one per batch of tool calls
plus one for preparation. Bounds: 5 seconds per call, no automatic Google retries,
16 calls per turn, 28 KB of state per request, and the turn's own deadline.
The native endpoint, model (`gemini-decision-1`) and bounds are fixed in code.

The classifier cannot prove arithmetic or an allergen claim. It only flags narrative
that the supplied records do not support.

Output review also receives the latest customer request, up to four earlier customer
messages, and up to five bounded recipe titles/summaries from successful discovery
tools. These are context, not purchase authority or dietary proof. The questions
explicitly distinguish recipe ideas, dietary requests, portion/budget questions and
explanations of confirmation from claims about verified products, prices, stock or
completed purchases. Food planning does not require purchase records. Actual
unsupported claims still block the reply; thresholds and purchasing controls are
unchanged. An empty-state rejection no longer asks the customer to repeat the same
message.

## Modes and failure behaviour

| `GUARDRAIL_MODE` | Behaviour |
| --- | --- |
| `enforce` (default) | A failed, uncertain, malformed or unavailable required check never becomes "allowed". New baskets are blocked; reading purchases and the confirmation API keep working. |
| `shadow` | Every check runs and is logged; nothing is blocked or withheld. Use it to collect labelled evidence. It provides **no** protection. |
| `off` | No classifier calls. Deterministic controls only. |

`GUARDRAIL_PROVIDER=google` (default) uses `GEMINI_API_KEY`, sent only to Google's
fixed native endpoint. Without that key every check is `unavailable` and no request is
sent, so in `enforce` mode chat turns fail with a retryable `GUARDRAIL_UNAVAILABLE`.
Shadow and enforce send minimized customer messages, catalog text and the
assistant's reply to Google. No buyer IDs, cookies, CSRF tokens or other credentials
are sent. Explicit legacy OpenRouter selection uses `LLM_API_KEY` only when
`LLM_BASE_URL` is on `openrouter.ai`.

Thresholds are on the risk probability: ≤ 0.2 passes, ≥ 0.8 fails, and anything
between is uncertain. They are **provisional** and enforced by default: re-select
them from the labelled live evaluation, and switch to `shadow` if false blocks appear.

Each check logs one line on `aimo.guardrails`: turn ID, boundary, mode, verdict,
policy version, served model, latency, error category, failed/uncertain question
names and probabilities. Conversation text and keys are never logged.

## Tests and evaluation

- Deterministic backend controls: `tests/test_guardrails_integration.py`
  (cross-buyer IDs, exact-revision confirmation and duplicate prevention behind an
  enforced guard, chat limits, minimised persisted context), plus the existing
  `test_agent*.py`, `test_conversations.py` and `test_http.py`.
- Mocked guardrail integration: `tests/test_guardrails.py`, with a fake Decisions
  provider and authored probabilities. These tests check wiring and failure
  behaviour. Native Google contracts are covered by `tests/test_google_providers.py`.
  Fake-provider tests do **not** measure detection accuracy.
- Live classifier evaluation (opt-in, never in CI): `uv run python
  scripts/evaluate_guardrails.py --write docs/guardrail-evaluation.json`. It runs
  authored English/Finnish/Swedish cases and reports per boundary: samples,
  missed attacks, false blocks, uncertain cases and latency. It is a small
  synthetic sample, not a guarantee.

Not covered: jailbreak-proof detection; semantic screening of imported recipe text from the recipe tools (results are wrapped as data, and the displayed meal-plan fields are reviewed at output, but summaries, instructions and notes are not screened before the model reads them); recipe arithmetic and deterministic
per-portion bounds (see `internal-agent.md`); trusted constraint provenance
(budgets and diets are inferred from customer text, so the earliest constraints
can fall outside a long prepare-check window); and non-English/Finnish coverage
beyond the sample.
