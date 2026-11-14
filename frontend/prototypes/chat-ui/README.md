# [PROTOTYPE] Chat purchasing confirmation UI variants

**Throwaway.** Built for [#26](https://github.com/Junction-Best-Team/Main-Application/issues/26),
[#27](https://github.com/Junction-Best-Team/Main-Application/issues/27) and
[#28](https://github.com/Junction-Best-Team/Main-Application/issues/28) under the
[#24](https://github.com/Junction-Best-Team/Main-Application/issues/24) wayfinding map. Not shipped to
`develop`, not built by root CI, not wired to any backend. Fake JSON only.

**Not the Persons 2/3 integration path.** For the real product API (session →
conversation/SSE → proposal → revision-bound confirm), use root `frontend/` with
`uv run aimo serve` and follow [`docs/run-notes.md`](../../../docs/run-notes.md).

## Run it

```sh
cd frontend/prototypes/chat-ui
npm install
npm run dev
```

Open the printed local URL (default `http://127.0.0.1:5183`). Sign in with any username/password
(try `baduser` to see the error state). Use the floating bar pinned to the bottom of every page to:

- Switch the **confirmation variant** — `sticky`, `modal`, `inline` — also settable directly via
  `?variant=sticky|modal|inline` in the URL. The variant persists across navigation.
- Switch the **scenario** to play the error/empty/loading/reconnect states without touching code:
  default, SSE reconnecting, next send fails (one-shot, then retries), empty purchase list, slow
  network.
- **Reset demo data** back to the initial fixtures.

## What's the same in all three variants

Everything except the confirmation UI, per the [#25 parity inventory](https://github.com/Junction-Best-Team/Main-Application/issues/25):

1. Login + session chrome
2. Conversation list + new/resume chat
3. Transcript (text + meal plan + basket link) + busy + send/retry
4. Reconnect messaging (faked via the scenario switch, no real SSE)
5. Purchase list
6. Basket detail with exact terms + confirm/reject + terms-changed recovery
7. Legacy `/approvals/:id` still opens historical detail (try the "superseded" purchase in the list)
8. Error / empty / loading states

## What differs — the one intentional difference

- **`sticky`** (#26): the basket page's decision panel is replaced by a bar fixed to the bottom of
  the viewport, restating the total and Confirm/Reject while you scroll the purchase sheet.
- **`modal`** (#27): the basket page shows a plain summary; a **Review & confirm…** button opens a
  modal dialog that restates the exact terms (destination, delivery date, revision, total) before
  Confirm/Reject.
- **`inline`** (#28): the proposal card inside the chat **thread** itself carries Confirm/Reject.
  Basket detail still has the same action for parity with the checklist above, labelled as the
  secondary path, with a link back to the conversation.

In every variant, confirm/reject is the same authenticated, revision-bound action
(`store.confirm(proposalId, revision)` / `store.reject(...)`) — chat text never triggers it. See
`src/confirmFlow.ts`.

## Try the "terms changed" recovery

Open the **Weekly oat milk restock** conversation (or `/purchases/prop-conflict` directly) and
confirm it. The fake backend simulates a race: the first confirm comes back "terms changed during
verification", the total moves, and you must confirm again — in whichever variant's chrome you're
currently viewing.

## Parity baseline and known simplifications

Structure, routes, copy and CSS classes are adapted from the real `frontend/src/main.tsx` /
`frontend/src/style.css` (PR [#13](https://github.com/Junction-Best-Team/Main-Application/pull/13) /
[#15](https://github.com/Junction-Best-Team/Main-Application/pull/15) chat surface) and the closed
research comment on [#25](https://github.com/Junction-Best-Team/Main-Application/issues/25). Known,
deliberate simplifications for a throwaway prototype (see `src/store.ts`):

- No real backend, SSE, CSRF or session cookies — `src/store.ts` is an in-memory fake with
  simulated latency. Reload the page to reset, or use "Reset demo data".
- Purchase list pagination is not wired (only one fixture page of items).
- The "superseded" fixture's "View current revision" link resolves the fixture directly, rather
  than simulating a second server round trip.

## Files

Entirely self-contained under this folder (own `package.json`/lockfile/`tsconfig.json`), so it
can't affect the real `frontend/` build, lint, or tests. See `src/App.tsx` for routing, `src/store.ts`
for the fake backend, `src/ConfirmPanels.tsx` + `src/InlineThreadCard.tsx` for the three confirmation
chrome variants, and `src/fixtures.ts` for the carbonara-style meal plan + proposal fixtures.
