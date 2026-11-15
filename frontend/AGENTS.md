# Frontend agent guide

Read the repository `AGENTS.md`, this file, and `docs/architecture.md` before
changing this package. `README.md` has setup commands; `docs/development.md`
explains extension patterns; `docs/testing.md` describes checks and fixtures.

## Scope and ownership

- `frontend/` is the production Vite/React package built by Docker and root CI.
  Keep this task's implementation here. `prototypes/chat-ui/` is an isolated
  historical mock app; do not import its store, fixtures or components into
  production. Coordinate changes to shared UI and contracts with teammates.
- `src/main.tsx` mounts React and loads styles. `src/app/` composes providers,
  routes and the application shell. Keep feature behavior out of both.
- A feature owns its `pages/`, `components/`, `hooks/`, `api/` and, where needed,
  `model/`. Pages compose a screen; hooks own asynchronous state/effects;
  components render typed props; API modules own endpoint paths/payloads.
- `src/shared/` contains reusable code with no dependency on `app/` or features.
  ESLint enforces this direction and prevents features importing `app/` or
  prototype code. Do not add empty folders or speculative abstractions.
- Import specific modules directly. Move a component to `shared/components/`
  only when multiple features need it. Feature-specific UI stays in its feature.

## Contracts to retain

- Backend Python models own the browser contract. Never hand-edit
  `src/shared/api/schema.ts` or `openapi.json`; regenerate using the README.
- JSON requests use `shared/api/client.ts`. Keep cookie authentication and
  explicit session-bound CSRF headers on writes. Never put private keys in
  browser variables, source or test artifacts.
- Confirmation is an explicit user action for an exact proposal revision.
  Preserve its stable retry key, revalidation, blocked states, second click
  after revised terms, historical approval links and mock-order wording.
- Keep session expiry handling, SSE cleanup/reconnect behavior, visible-tab
  refresh, pagination and message retry recovery when moving components.
- Server-authoritative data comes from feature API modules. Do not introduce
  a mock fallback, a second client-side copy of purchase authority, or a new
  state management library just to move code.

## Styling and validation

- Follow `../ui/DESIGN.md` and its desktop/mobile references. Tokens, preflight and base rules live in
  `src/styles/theme.css`; legacy CSS is removed. Import global CSS only through the entry point.
- Use `npm run check` and the relevant browser tests from this directory.
  `npm test` starts Vite automatically for credential-free UI fixtures;
  `npm run test:integration` explicitly requires the fixture backend/database.
- Add behavioral regression coverage when changing behavior; avoid tests that
  merely duplicate the folder structure. Check desktop and mobile when UI moves.
- Report actual commands and limitations. Follow root PR rules; do not merge or
  deploy as part of the current chat/frontend task.
