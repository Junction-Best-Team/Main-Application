# Frontend checks

Run commands from `frontend/` unless a command states otherwise.

## Static checks and production build

```sh
npm ci
npm run check
```

`check` runs local Prettier validation and then `build`, which runs ESLint,
strict TypeScript and Vite build. The existing CI and Docker commands enforce
the build checks without workflow changes; formatting and browser checks stay
local per the repository CI policy. ESLint
checks hook rules/dependencies and import direction. Generated schema, build
output and the historical prototype are excluded from lint/format rewriting.
`npm run format` updates maintained source/config/docs. Production output is
`dist/`; the existing Dockerfile and CI still use this package.

## UI behavior without a backend

```sh
npm exec -- playwright install chromium
npm test
```

The default Playwright configuration starts Vite at `127.0.0.1:5173`, or reuses
an existing local server outside CI. UI specs intercept API routes and require
no credentials. Live backend specs skip unless explicitly enabled.
`npm run test:ui` selects only the credential-free chat suite.

To test an already running frontend at another origin:

```sh
BASE_URL=http://localhost:5174 npm run test:ui
```

Supplying `BASE_URL` disables automatic Vite startup. Never point fixture-based
checks at a production customer session.

UI regressions cover Home, desktop/mobile navigation, SKU cards, Overview
confirmation/drawer, blocked states and sparse accepted-order pagination, plus conversation creation/refresh, lost-response retry
keys, sign-in/deep links, explicit confirmation, revised terms requiring another
click, historical closed approvals, purchase history/refresh failures and
server-side unfinished-turn recovery (including an interrupted SSE snapshot),
unresolved recipe quantities and saved-recipe/free-form basket evidence, and
Memory (`e2e/preferences.spec.ts`: scopes, empty/error states,
typed create/edit, revision conflicts, forget, session expiry, safe text,
navigation and mobile). They
prove UI behavior against authored responses, not live provider, database or
supplier integration.

`e2e/chat-activity.spec.ts` exercises real EventSource consumption with authored
activity snapshots: each tool call, failed/unfinished steps, active-to-complete
updates, refresh recovery, reduced motion and desktop/phone layouts. Backend
activity persistence and attempt fencing are covered by `tests/test_chat_activity.py`.

## Live fixture integration

```sh
# Start the fixture backend and its matching test database first (root README).
BASE_URL=http://localhost:8000 npm run test:integration
```

This opts into `e2e/approval.spec.ts`. Its historical-revision fixture uses `uv`
and `tests/browser_revision_fixture.py`, with a database matching the running
backend. It can create demo purchasing records. Use a dedicated local fixture
environment and read the root README's test setup. Backend/database/provider
setup is not performed by the frontend test runner.

## Visual verification

After layout changes inspect the affected screen at desktop and mobile widths,
including loading, empty, failed and successful states. Check keyboard focus,
readable purchase totals, no horizontal overflow and reachable actions.
For purchase UI also check pending, revised, expired, blocked, superseded and
accepted mock states. Screenshots support inspection; they are not a substitute
for the exact-revision/explicit-action behavior regressions.

Generated browser screenshots and Playwright results are local artifacts.
Report the commands that passed and distinguish mocked browser coverage from
live integration. Do not claim a production deployment from local checks.

Draft-cart cases in `e2e/chat.spec.ts` stream an empty chat through unresolved ingredients,
selected products, checked unit prices, refresh and prepared-basket confirmation at
1440/390/320px. Drafts expose no confirmation control; fixture prices remain labelled.
Use a dedicated Vite port with `BASE_URL` when another checkout has a local server.
