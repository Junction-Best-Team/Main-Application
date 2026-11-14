# Frontend checks

Run commands from `frontend/` unless a command states otherwise.

## Static checks and production build

```sh
npm ci
npm run check
```

`check` runs `build`, which runs ESLint, Prettier check, strict TypeScript and
Vite build. The existing CI and Docker build commands therefore enforce these
checks without workflow changes. ESLint
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

Current UI regressions cover conversation creation/refresh, lost-response retry
keys, sign-in/deep links, explicit confirmation, revised terms requiring another
click, historical closed approvals, purchase history/refresh failures and
server-side unfinished-turn recovery (including an interrupted SSE snapshot),
unresolved recipe quantities and saved-recipe/free-form basket evidence. They
prove UI behavior against authored responses, not live provider, database or
supplier integration.

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
