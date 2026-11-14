# [PROTOTYPE] Chat purchasing UI

**Throwaway.** Built for [#26](https://github.com/Junction-Best-Team/Main-Application/issues/26),
[#27](https://github.com/Junction-Best-Team/Main-Application/issues/27) and
[#28](https://github.com/Junction-Best-Team/Main-Application/issues/28) under the
[#24](https://github.com/Junction-Best-Team/Main-Application/issues/24) wayfinding map. Not shipped to
`develop`, not built by root CI, not wired to any backend. Fake JSON only.

## Run it

```sh
cd frontend/prototypes/chat-ui
npm install
npm run dev
```

Open the printed local URL (default `http://127.0.0.1:5183`). Sign in with any username/password
(try `baduser` to see the error state). Use the floating bar pinned to the bottom of every page to:

- Switch the **scenario** to play the error/empty/loading/reconnect states without touching code:
  default, SSE reconnecting, next send fails (one-shot, then retries), empty purchase list, slow
  network.
- **Reset demo data** back to the initial fixtures.

## Confirmation

There is a single confirmation path: the Overview panel on the Request screen (a right-hand column on
desktop, an expandable bottom drawer on mobile), with "Approve & Push to Dispatch" and Reject. The chat
thread has no decision controls; `/purchases/:id` only shows placed (accepted) orders. Confirm/reject is an authenticated, revision-bound action
(`store.confirm(proposalId, revision)` / `store.reject(...)`) — chat text never triggers it. See
`src/confirmFlow.ts`.

## Try the "terms changed" recovery

Open the **Weekly oat milk restock** conversation and approve it in the Overview panel. The fake backend simulates a race: the first confirm comes back "terms changed during
verification", the total moves, and you must approve again — in the Overview panel.

## Parity baseline and known simplifications

Structure, routes, copy and CSS classes are adapted from the real `frontend/src/main.tsx` /
`frontend/src/style.css` (PR [#13](https://github.com/Junction-Best-Team/Main-Application/pull/13) /
[#15](https://github.com/Junction-Best-Team/Main-Application/pull/15) chat surface) and the closed
research comment on [#25](https://github.com/Junction-Best-Team/Main-Application/issues/25). Known,
deliberate simplifications for a throwaway prototype (see `src/store.ts`):

- No real backend, SSE, CSRF or session cookies — `src/store.ts` is an in-memory fake with
  simulated latency. Reload the page to reset, or use "Reset demo data".
- Purchase list paging is only exercised by the "Many past orders (paged)" scenario; the default is one page.
- The "superseded" fixture's "View current revision" link resolves the fixture directly, rather
  than simulating a second server round trip.

## Files

Entirely self-contained under this folder (own `package.json`/lockfile/`tsconfig.json`), so it
can't affect the real `frontend/` build, lint, or tests. See `src/App.tsx` for routing (Home `/`, Request
`/request` and `/conversations/:id`, Past Orders `/purchases`), `src/AppShell.tsx` for the sidebar / mobile
menu shell, `src/mock.ts` + `src/placeholders.tsx` for inert MOCK placeholders, `src/store.ts`
for the fake backend, `src/OverviewPanel.tsx` for the Overview (confirmation) panel, and `src/fixtures.ts` for the carbonara-style meal plan + proposal fixtures.

## E2E

`e2e/` holds the Playwright specs (import `test` from `e2e/test.ts`, which serves Google Fonts from a
local cache so the outside network can't stall a page load or screenshot), run at a desktop
(1440×1000) and a mobile (390×844) viewport. From this folder (own `@playwright/test`
devDependency; starts or reuses the dev server on port 5183):

```sh
npm ci
npx playwright install chromium
npx playwright test
```
