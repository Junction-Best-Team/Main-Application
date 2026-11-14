# Bare-min buyer path — run notes (Persons 2/3)

Integration target for [spec #65](https://github.com/Junction-Best-Team/Main-Application/issues/65) /
[handoff #70](https://github.com/Junction-Best-Team/Main-Application/issues/70) on
`develop` (landed from the practical docs / e2e slice; see
[issue #134](https://github.com/Junction-Best-Team/Main-Application/issues/134)).

**Use the real product stack** (`frontend/` + `uv run aimo serve`). Do **not** use
`frontend/prototypes/chat-ui` (fake JSON only) for agent or tools work.

Designer `ui/` skins are **out of acceptance** for this handoff.

API contracts (routes, SSE, confirm discriminators):
[`api-stub-phase0.md`](api-stub-phase0.md).

## Start

Follow root `README.md` setup (`uv sync`, `aimo configure`, Postgres via
`docker compose`, `aimo migrate` / `seed`, catalog via `aimo fixture-catalog` or
full ingest). Set `LLM_API_KEY` in `.env` for chat turns. Keep
`UPSTREAM_MODE=fixture` unless you intentionally switch commercial evidence
(still no supplier checkout).

**Option A — production-shaped (API serves the built UI):**

```sh
npm ci --prefix frontend
npm run build --prefix frontend
uv run aimo serve
```

Open http://localhost:8000/

**Option B — Vite + API (hot reload):**

```sh
# Terminal 1 — set PUBLIC_BASE_URL=http://localhost:5173 in .env first
uv run aimo serve
# Terminal 2
npm ci --prefix frontend
npm run dev --prefix frontend
```

Open http://localhost:5173/ (Vite proxies `/api` → `:8000`).

Sign in as **buyer**. Password is `DEMO_BUYER_PASSWORD` from `.env` (never commit it).

## Path to exercise

Product IA after the Request / Overview cutover: **Home** is `/`, new chat is
`/request`, open threads stay under `/conversations/{id}`, and revision-bound
confirm lives in the **Overview** panel (or Past Orders for placed receipts).

1. **Session** — sign in; reload should restore; sign out clears the cookie.
2. **Conversation / SSE** — from Home or Request, create or open a conversation;
   send a message (CSRF + `idempotency_key`); watch the thread update from SSE
   `conversation` full snapshots (busy affordance while a turn runs).
3. **Proposal detail** — open baskets stay in Overview; placed mock orders link
   to `/purchases/{proposal_id}` for the receipt.
4. **Revision-bound confirm** — click **Approve & Push to Dispatch** in Overview
   (chat text must never buy). Body is
   `{ proposal_id, revision, idempotency_key }` with session cookie + `X-CSRF-Token`.
   Repeat the same key → saved receipt; stale revision → re-review; expired/closed →
   plain error. Receipt may show a mock-acceptance label (no supplier checkout).

Suggested prompt once chat is up: ask for ingredients for 200 portions of carbonara,
then clarify delivery / site / budget as the assistant asks.

## Out of path

| Thing | Role |
| --- | --- |
| `frontend/prototypes/chat-ui` | Throwaway confirmation-variant demos; fake JSON; **not** P2/P3 integration |
| Playwright e2e (default) | Mocks API at the browser edge; regression only, not the live path |
| Designer `ui/` skin pass | Deferred; not required to integrate |
| `/mcp`, `/api/agent/*` | Removed; 404 |

## Smoke without the browser

```sh
uv run python scripts/demo.py
```

Then finish confirm in the product UI — CLI chat never commits.
