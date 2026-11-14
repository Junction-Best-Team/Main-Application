# Internal meal-purchasing assistant

The application calls `aimo.agent.run_turn(identity, messages, service)` with the
server's trusted buyer-scoped agent and persisted chat messages. The provider
receives conversation text and tool results; it never receives browser cookies,
CSRF tokens, database credentials or its own API key in the conversation.

Set `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS` and
`LLM_MAX_TOOL_ROUNDS` on the server. The default provider uses the OpenAI-compatible
`/chat/completions` function-calling protocol. Embedding configuration remains
independent. Missing or rejected provider credentials produce an actionable error,
not a pretend assistant response. Provider compatibility follows the official
[function-calling protocol](https://developers.openai.com/api/docs/guides/function-calling).

The typed registry calls `Service` directly for catalog search, product detail,
policy, price/availability, preparation, proposal status and saved receipts. It
also publishes the shared `MealPlan`. Model arguments cannot choose an identity,
change policy, supply permissions, approve a recipe as purchasing authority, or
commit an order. Preparation keys are generated from the persisted turn ID (one preparation payload per turn), so retries do not depend on a model-generated key.

The assistant asks for delivery, dietary needs and budget, proposes ingredient
quantities, and matches products from the actual catalog. Every required
ingredient must have a product loaded through `get_product`; basket amounts and
units must exactly match the published complete plan. An incomplete match remains
a draft and cannot prepare a partial meal silently. Recipe amounts are estimates
for customer review. The existing backend validates quantities, supported dietary
evidence, commercial evidence, policy and approval requirements. Unsupported
dietary constraints require manual resolution; chat never verifies them.

Only the product's authenticated customer confirmation action can resume and
commit a purchase. Existing product scope and authority still apply. The agent
has no confirmation or commit tool, including when the customer types “approved”.
Purchase status and basket links come from successful buyer-scoped `Service`
results, not identifiers invented by the model. Persisted customer decisions and
receipts are read back on later turns. Ordering remains mock: there is no supplier
checkout or inventory reservation.

Each provider request has a configured timeout, at most one retry for transient
failures, and no early retry when the provider supplies `Retry-After`. Turns have a
90-second provider budget, a configured round limit, at most 12 calls per response,
and stop after four tool errors. Supplier lookups retain their own bounded retry
behavior. If the provider fails after preparation, the successful basket is still
returned to the application for persistence and customer review, including an
empty final provider reply. After successful preparation, this turn's meal plan
and purchase terms are fixed; identical retries remain allowed. Recipe or terms
changes need a new customer message. Reading another saved purchase does not
replace the prepared basket's association with its meal plan.

Validation on 2026-11-14: `uv run ruff check src/aimo/agent.py tests/test_agent.py`
and `uv run pytest -q tests/test_agent.py` passed (38 tests). These use a fake
provider and service; they do not assert a live provider/supplier checkout.
