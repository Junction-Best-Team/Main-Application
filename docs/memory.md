# Buyer and user memory

The chat assistant remembers facts, defaults, preferences and workflow instructions
that a customer **explicitly** asks it to keep. Customers manage it in chat or on
the **Memory** screen (`/settings/preferences`, see
[Browser screen](#browser-screen)). Code: `src/aimo/memory.py` (the one
storage/validation service), `src/aimo/memory_schemas.py` (contracts), migration
`012_buyer_user_memory.sql`, tools in `agent_tools.py`, prompt in `agent.py`, the
semantic write check in `guardrails.py`, routes in `api.py`.

## Scopes

| Scope | Owner | Who can read/manage it | Example |
| --- | --- | --- | --- |
| `buyer` (shared) | The buyer account | Every active approver identity of that buyer | "We usually plan for 200 portions", "Prefer 1 L cream cartons" |
| `user` (personal) | One human identity (`identities.id`) within the buyer | Only that identity | "Keep my replies short", "Show cheaper alternatives before preparing a basket" |

Requests name the scope as `buyer` or `self`; the server resolves the actual owner
from the signed-in session or the persisted chat turn. There is no users table,
kitchen entity or new role. Delivery destinations stay strings checked by policy.
Managing memory is not policy administration and grants no purchasing authority.

**Visibility caveat.** Personal memories are loaded only into turns *requested by
their owner*, and only their owner can list or change them. Conversations, however,
are shared by every user of the buyer. The customer's own "remember…" message, the
assistant's reply and the server's "Memory: Saved your personal memory: <key>"
notice are visible to colleagues in that conversation's history. The notice names
the key, not the value, and the assistant is told not to repeat personal contents
needlessly; personal memory is **not** private from conversation history.

The message's original author is stored in `conversation_turns.submitted_by` and
does not change on retry. If a colleague retries a failed turn, purchasing can
resume but memory loading and tools are unavailable for that attempt. The original
author can retry their own failed turn with memory enabled. Turns created before
migration 012 have no recorded author and also run without memory; the migration
does not infer an author from the latest executor.

## Supported kinds and keys

Each item has a kind, a stable key and a typed JSON value. Unknown keys and extra
fields are rejected; there is no free-form JSON blob or growing summary.

| Kind | Key | Value |
| --- | --- | --- |
| `default` (fact/default) | `default.portions` | `{"portions": 1–10000}` |
| `default` | `default.delivery_destination` | `{"destination": "≤120 chars"}`; still checked against allowed destinations |
| `default` | `default.dietary_requirements` | `{"lactose_free": bool, "milk_free": bool}` |
| `preference` | `preference.reply_style` | `{"length": "short"/"normal"/"detailed", "language": "en"/"fi"/"sv" (optional)}` |
| `preference` | `preference.pack_size.<topic>` | `{"ingredient", "amount" (>0), "unit", "note"?}`, e.g. cream 1 L |
| `preference` | `preference.product.<topic>` | `{"ingredient", "preference" (≤200), "product_ids" (≤5 hints)}`; IDs never extend product scope |
| `preference` | `preference.note.<topic>` | `{"text": "≤280 chars"}` |
| `instruction` (assistant instruction) | `instruction.<topic>` | `{"text": "≤280 chars"}` |

`<topic>` is 1–40 characters of `a–z`, `0–9`, `_`. Optional `description` ≤200
characters. The database repeats these as constraints (key pattern and kind prefix,
object values ≤1,024 bytes, owner present only for personal scope, owners/creators
and source conversation in the same buyer, one item per key and owner).

Not memory: recipes, recipe plans or favourites, conversation or purchase history,
prices, stock, dietary evidence, credentials, payment or account details,
permissions. A deterministic screen rejects values that look like passwords, API
keys, tokens, card/account numbers or IBANs (`MEMORY_SENSITIVE_DATA`); it is a floor,
not a complete classifier.

## Limits

| Limit | Value | Constant |
| --- | --- | --- |
| Items per owner | 50 personal per user; 50 shared per buyer | `memory.MAX_PER_OWNER` |
| Text / description | 280 / 200 characters | `memory_schemas` |
| Stored value | 1,024 bytes | DB check |
| Automatic context | ≤20 items and ≤6,000 characters | `CONTEXT_MAX_ITEMS`, `CONTEXT_MAX_CHARS` |
| `search_memory` page | ≤10 items, offset ≤90 | `MemoryToolSearch` |
| `GET /api/memories` page | ≤50 items, offset ≤100 | `MemorySearch` |

## Automatic loading

Before each model turn the worker loads the requesting user's personal items and
the buyer's shared items (never another user's) and adds them as a second system
message after the rules, labelled as customer-saved context below the
instructions, purchasing policy and tool evidence. Each item carries its ID,
scope, key, value, description and revision so the assistant can update the exact
item. Order is deterministic:

1. fixed facts (`default.*`, `preference.reply_style`);
2. items whose text matches the latest customer message (PostgreSQL `simple`
   full-text prefix match, ranked);
3. instructions; 4. other preferences.

Within a tier personal items come before shared ones, then rank, most recent and ID.
Loading stops at the item or character budget and reports `omitted`; the assistant
uses `search_memory` for the rest. No embeddings, vector store or second model call.

If a personal and a shared item have the same key, the personal one comes first
and wins for that user. A current instruction overrides a saved default for that
purchase only and does not rewrite the stored item. Saved defaults do not remove
clarification or recipe review. Under guardrail enforcement the preparation check
only counts what the customer said in the conversation, so the assistant should
state the saved destination it intends to use and get it confirmed.

## Assistant tools

Two model-facing tools (registered in `ToolSession`; the purchasing and recipe
tools are unchanged):

- `search_memory` — `query` (≤200), `scope` (`all`/`buyer`/`self`), `kind`,
  `offset`, `limit`. Only this buyer's shared and this user's personal items.
- `manage_memory` — `action` `save` (`scope`, `key`, `value`, `description?`),
  `update` (`memory_id`, `expected_revision`, `value`, `description?`) or `delete`
  (`memory_id`, `expected_revision`). Returns the authoritative status, ID, revision
  and item. Owner, buyer, creator, source message and permissions are not fields;
  extra arguments are rejected.

Saving an existing key fails with `MEMORY_EXISTS` and names the existing ID and
revision: nothing is overwritten by a fuzzy match. A wrong expected revision fails
with `MEMORY_REVISION_CONFLICT`. Successful writes add a server-authored notice to
the reply with the scope, e.g. "Memory: Saved shared buyer memory (used for
everyone in this account): default.portions." The model cannot fake that notice.

### Explicit intent

Writes need lasting intent in the **current** customer message ("remember",
"from now on", "change our usual…", "forget…"). An explicit request is enough;
there is no second approval step. Defences, in order:

1. **Binding (deterministic).** The server requires the persisted turn's latest
   executor (`requested_by`) to match its original author (`submitted_by`), rechecks
   they are an active approver of the buyer, and
   records the turn's own user message as the source. The model cannot choose the
   source, owner or creator; a model flag like `explicit_user_request` is not a field.
2. **Semantic check (guardrails, `memory_write` boundary).** Under `enforce` each
   write is reviewed by Jev against the persisted customer messages only:
   `persistence_intent`, `matches_request`, `scope`, `no_authority`. Product,
   supplier and recipe text never enters this state; the preceding assistant reply
   is included but marked model-authored and counts only if the customer explicitly
   agrees to that exact proposal. A failed, uncertain or unchecked input screen
   refuses the write (`MEMORY_INTENT_UNCONFIRMED`, `GUARDRAIL_UNCHECKED_REQUEST`,
   `GUARDRAIL_UNAVAILABLE`) and the assistant must ask instead.
3. **Prompt rules** tell the model not to save one-off requests, inferred patterns
   or third-party text, and to ask when scope or target is ambiguous.

With `GUARDRAIL_MODE=off` only 1 and 3 apply: the model's judgement decides
whether the customer meant it. Neither the classifier nor the prompt is complete
enforcement; nothing in memory can authorize a purchase anyway.

### What memory cannot do

Memory is never purchasing authority. Policy versions, approved product scope,
identity authority, commercial/dietary evidence checks and the authenticated
exact-revision confirmation are unchanged and are not readable from memory. A saved
"approve automatically" instruction or an out-of-scope product hint has no effect
on outcomes (`tests/test_memory.py::test_saved_memory_cannot_bypass_policy_evidence_or_confirmation`).

## Management API

Authenticated with the browser session. Writes need the exact `Origin` and the
session-bound `X-CSRF-Token`. Errors use the usual `{"error": {"code", "message"}}`.
A management-API write is itself an explicit user action and needs no chat message.

| Method and path | Body | Notes |
| --- | --- | --- |
| `GET /api/memories?scope=all\|buyer\|self&kind=&q=&offset=&limit=` | — | Shared plus own personal items; `next_offset` for paging |
| `POST /api/memories` | `{"scope": "buyer", "key": "default.portions", "value": {"portions": 200}, "description": "Usual lunch", "idempotency_key": "memory-create-2026-01"}` | `status` `created` |
| `PUT /api/memories/{id}` | `{"expected_revision": 1, "value": {"portions": 150}, "idempotency_key": "memory-update-2026-02"}` | `updated`, or `unchanged` without a revision bump |
| `POST /api/memories/{id}/delete` | `{"expected_revision": 2, "idempotency_key": "memory-forget-2026-03"}` | `deleted`; the item is gone |

Response (`MemoryMutationResponse`): `status`, `memory_id`, `revision`, `memory`
(the full item or `null` after delete) and `replayed`. Codes: 401 `UNAUTHENTICATED`,
403 `ORIGIN_REJECTED`/`CSRF_REJECTED`/`AUTHORITY_REVOKED`, 404 `MEMORY_NOT_FOUND`
(also for another user's or buyer's item), 409 `MEMORY_EXISTS`,
`MEMORY_REVISION_CONFLICT`, `MEMORY_LIMIT`, `IDEMPOTENCY_CONFLICT`, 422 validation,
`MEMORY_VALUE_INVALID`, `MEMORY_SENSITIVE_DATA`. Generated browser types:
`frontend/openapi.json`, `frontend/src/shared/api/schema.ts`.

## Browser screen

`/settings/preferences` (`frontend/src/features/preferences/`) is the **Memory**
page. Its *Personal* (`scope=self`) and *Shared with buyer* (`scope=buyer`) tabs
show compact rows with Edit and Forget actions. Updated timestamps and source
conversation links expand under Details. A single Add memory action offers only
the keys above, as typed fields (portions, destination,
dietary flags, reply length/language, pack size, product preference, note,
instruction); family topics are derived from the ingredient or text, never typed
by the customer. Writes use the session CSRF token, the item's revision and an
idempotency key reused only for an identical retry. A conflict keeps the draft
and offers *Load latest version*; an item leaves the list only after the server
confirms. Lists live only in page state, keyed by the signed-in identity. Links
are in the sidebar/mobile account menu and the chat header.

Known contract gaps for the browser (deliberately not worked around):

- `ChatMessage` has no structured memory-change metadata, so chat shows the
  ordinary reply (including the server's "Memory: …" notice) without a badge.
- `MemoryUpdate` keeps the stored description when none is sent, so a saved
  description can be reworded but not removed.
- Product preference `product_ids` hints are preserved on edit but not editable.
- No reversible forget exists, so the screen offers no Undo.

## Concurrency, retries and forgetting

- Every write locks the buyer row, then (chat only) share-locks the turn row, then
  the memory row. The turn must still be `running` with the same `attempt`, an
  unexpired lease and matching `requested_by` and `submitted_by`, so a superseded or completed worker
  attempt fails with `TURN_REPLACED` and writes nothing. A reclaim that changes the
  attempt waits for an in-flight write to commit.
- Updates and deletes need the expected revision; there is no last-writer-wins.
- Idempotency is durable in `memory_mutations` per buyer, human and key. API keys
  come from the client. Chat keys are `chat:<turn>:<action>:<target>`, derived from
  the persisted turn, not provider tool-call IDs, so a retried attempt replays
  instead of duplicating. Reusing a key with different content is
  `IDEMPOTENCY_CONFLICT`. Expected revision is excluded from the request hash so a
  retried attempt that re-read the item still replays.
- The chat tool resolves an earlier mutation before reading the live item or
  repeating the semantic write check. A replayed delete succeeds even though its
  item is gone. A replayed save/update whose item was forgotten reports
  `forgotten_since` and an "Already forgotten" notice; it never recreates the item.
  Replays still recheck the active author and fence the worker attempt.
- Forget deletes the row; it disappears from loading, search and the API. Earlier
  mutation rows keep only minimal metadata (action, outcome, ID, revision, actor,
  time): their request hashes are cleared, so no copy or fingerprint of the content
  remains. Replaying an old save key returns `deleted` and never recreates it. The
  chat messages that asked to save or forget are separate history and remain.

## Operations

Migration `012_buyer_user_memory.sql` is additive: two tables, a nullable
`conversation_turns.submitted_by` author column, three composite
unique constraints on existing tables (always satisfied because `id` is already the
key) and indexes. Apply it as usual (`uv run aimo migrate`, or the release
migration Job). The runtime grant refresh in `permissions.py` covers the new
tables with ordinary SELECT/INSERT/UPDATE/DELETE; identity, buyer and policy
provisioning stay revoked (`tests/test_runtime_permissions.py`). No new service,
worker, setting or secret.
