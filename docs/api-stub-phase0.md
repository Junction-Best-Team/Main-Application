# Phase-0 product API stub

Reference for Persons 2 and 3 to integrate against the bare-min chat purchasing
path on `fm/junction-chat-ui-prototypes` without waiting on the designer `ui/`
skin pass. This documents the one existing FastAPI app (`src/aimo/api.py`,
`src/aimo/schemas.py`, `src/aimo/chat_schemas.py`) — it is not a second HTTP
server, and nothing here invents a new contract. Full behavior and rationale:
[`chat-purchasing.md`](chat-purchasing.md). `/mcp` and `/api/agent/*` are out of
scope for this bare-min path.

## Trust boundary

Chat text never buys. The assistant can draft a meal plan and prepare a basket,
but it has no confirm or commit tool, even if the customer types "approved" in
chat. Only `POST /api/purchases/{proposal_id}/confirm` — issued by the signed-in
browser with a matching session cookie, `X-CSRF-Token`, and same-origin
`Origin` — can commit an order. That call re-validates the exact revision,
current policy and buyer authority server-side before anything is persisted.

## Buyer product routes

All `/api/*` routes require the `aimo_session` cookie (set by `/api/login`) except
login itself. Mutating routes (`POST`) additionally require a same-origin
`Origin` header and `X-CSRF-Token: <csrf_token from /api/session>`; a mismatch
returns a `Problem` (`ORIGIN_REJECTED` / `CSRF_REJECTED`, 403).

| Method | Path | Purpose | Response |
| --- | --- | --- | --- |
| POST | `/api/login` | Sign in, set `aimo_session` cookie | `SessionResponse` |
| GET | `/api/session` | Restore session on reload | `SessionResponse` |
| POST | `/api/logout` | Clear session | 204 |
| GET | `/api/conversations` | List conversations | `ConversationList` |
| POST | `/api/conversations` | Start a conversation (idempotent) | `ConversationResponse` |
| GET | `/api/conversations/{id}` | Conversation snapshot (poll fallback) | `ConversationResponse` |
| POST | `/api/conversations/{id}/messages` | Send a chat message (idempotent) | `ConversationResponse` |
| GET | `/api/conversations/{id}/events` | SSE stream of snapshots | `text/event-stream` |
| GET | `/api/purchases` | Buyer's purchase history | `InboxResponse` |
| GET | `/api/purchases/{proposal_id}` | Proposal/purchase detail | `ProposalResponse` |
| POST | `/api/purchases/{proposal_id}/confirm` | Revision-bound confirm (idempotent) | `CommitResponse` |
| GET | `/api/approvals` | Buyer's approval inbox | `InboxResponse` |
| GET | `/api/approvals/{approval_id}` | Approval detail | `ProposalResponse` |
| POST | `/api/approvals/{approval_id}/decision` | Legacy approve/reject | `ProposalResponse` |

`idempotency_key` is required on every create/message/confirm body; reusing a key
with a different payload is a `Problem` (`IDEMPOTENCY_CONFLICT`). A repeated
confirm with the same key returns the saved receipt without touching the
supplier.

## SSE `conversation` event

`GET /api/conversations/{id}/events` authenticates once, then pushes the full,
persisted `ConversationResponse` on change — **a full-snapshot replace is the
source of truth**; the client never patches the thread incrementally. Frames
poll every 2s, close after a 25s deadline (client reconnects), and re-check
session revocation on every frame.

```
event: conversation
data: {"id":"...","title":"...","messages":[...],"purchases":[...],"busy":false,"retry_message":null}

: keep-alive

event: expired
data: {}
```

`: keep-alive` lines are comment heartbeats (no `event:`/`data:`, ignored by
`EventSource`). `event: expired` means the session was revoked mid-stream; the
client must re-authenticate, not retry the same stream.

## Example payloads

**`POST /api/login`** → **`SessionResponse`**

```json
// request
{ "username": "buyer-1", "password": "••••••••" }
// response
{ "username": "buyer-1", "buyer_id": "buyer-1", "csrf_token": "6f1c9a...e2" }
```

**`ConversationResponse`** (conversation detail / SSE `conversation` data)

```json
{
  "id": "4f6a0b8e-1a2b-4c3d-9e8f-123456789abc",
  "title": "Carbonara for four",
  "created_at": "2026-11-14T14:58:00Z",
  "updated_at": "2026-11-14T15:02:03Z",
  "messages": [
    { "id": 11, "role": "user", "text": "Carbonara for 4, Helsinki, Friday",
      "created_at": "2026-11-14T14:58:30Z", "meal_plan": null, "proposal_id": null },
    { "id": 12, "role": "assistant", "text": "Drafted a basket for review.",
      "created_at": "2026-11-14T15:02:03Z",
      "meal_plan": { "title": "Carbonara for four", "portions": 4,
        "ingredients": [{ "name": "Spaghetti", "amount": "500", "unit": "g", "product_id": "p-001" }],
        "notes": [] },
      "proposal_id": "b2b6c2b2-0000-4000-8000-000000000001" }
  ],
  "purchases": [ /* ProposalResponse items, see below */ ],
  "busy": false,
  "retry_message": null
}
```

**`ProposalResponse`** (purchase/approval detail)

```json
{
  "proposal_id": "b2b6c2b2-0000-4000-8000-000000000001",
  "revision": 1,
  "current_revision": 1,
  "committed_revision": null,
  "current_proposal_url": "/purchases/b2b6c2b2-0000-4000-8000-000000000001",
  "policy_version": 3,
  "policy_outcome": "ready_to_commit",
  "approval_status": "not_required",
  "order_status": "open",
  "reasons": [],
  "expires_at": "2026-11-14T15:30:00Z",
  "next_action": { "type": "commit", "tool": null, "poll_after_seconds": null },
  "approval_id": null,
  "approval_url": null,
  "order_id": null,
  "buyer_id": "buyer-1",
  "agent_id": "agent-buyer-1",
  "request": { "...": "PurchaseRequest" },
  "snapshot": { "...": "PurchaseSnapshot", "currency": "EUR", "gross_total": "18.4000" },
  "history": [],
  "can_decide": false
}
```

**`POST /api/purchases/{proposal_id}/confirm`**

```json
// request
{
  "proposal_id": "b2b6c2b2-0000-4000-8000-000000000001",
  "revision": 1,
  "idempotency_key": "confirm-2026-11-14-buyer1-0001"
}
```

Response is discriminated by `status`:

```json
// receipt: terms matched, order accepted (mock — no live supplier checkout)
{
  "status": "accepted_mock",
  "order_id": "7c1a2b3c-0000-4000-8000-000000000002",
  "proposal_id": "b2b6c2b2-0000-4000-8000-000000000001",
  "revision": 1,
  "policy_version": 3,
  "policy_outcome": "ready_to_commit",
  "approval_status": "not_required",
  "order_status": "accepted_mock",
  "reasons": [],
  "label": "Demo order — mock acceptance, no supplier checkout",
  "upstream_order_placed": false,
  "inventory_reserved": false,
  "buyer_id": "buyer-1",
  "gross_total": "18.4000",
  "currency": "EUR",
  "evidence_mode": "live",
  "accepted_at": "2026-11-14T15:05:00Z",
  "explanation": "...",
  "expires_at": "2026-11-14T15:30:00Z",
  "next_action": { "type": "complete", "tool": null, "poll_after_seconds": null }
}
```

```json
// revised: price/policy/authority changed since the client last saw this revision;
// no confirmation was recorded — the UI must show the new terms and require another click
{ "status": "revised", "proposal_id": "b2b6c2b2-0000-4000-8000-000000000001", "revision": 2, "...": "rest of ProposalResponse" }
```

```json
// problem/closed: confirm rejected outright (HTTP 4xx, not a CommitResponse body)
{ "error": { "code": "DECISION_CLOSED", "message": "This purchase is finalized, expired or under an older policy." } }
```

Other confirm `Problem` codes: `STALE_REVISION` (revision in body no longer
matches), `PROPOSAL_MISMATCH` (body/path proposal id disagree), `COMMIT_BLOCKED`
(policy/evidence not resolved), `APPROVAL_SCOPE` (amount/exception exceeds buyer
authority), `IDEMPOTENCY_CONFLICT` (key reused for different terms),
`CSRF_REJECTED` / `ORIGIN_REJECTED` (not an authenticated same-origin browser
call).

## Status

Synthesized from the live routes/schemas above on 2026-11-14 for
[issue #66](https://github.com/Junction-Best-Team/Main-Application/issues/66)
under [spec #65](https://github.com/Junction-Best-Team/Main-Application/issues/65).
No new server, route, or schema was added.
