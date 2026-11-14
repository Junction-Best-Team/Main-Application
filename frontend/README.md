# Aimo frontend

The production customer app: React 19, TypeScript, React Router, Vite 7 and
Tailwind CSS v4. FastAPI serves the built assets; Vite proxies `/api` during
local development. This package stays in the application repository so the
frontend, generated API contract, CI and production image evolve together.

## Start developing

Use the repository's Node **24.6.0** (`../.node-version`). From the repo root:

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
```

Open the Vite URL, normally `http://127.0.0.1:5173`. Start the backend on port
8000 using the root README. Set its `PUBLIC_BASE_URL` to the exact Vite origin
(including `localhost` versus `127.0.0.1`) for Origin validation. Sign in with
configured buyer credentials. Credentials and conversational provider keys
remain on the server. The product has no fake-login fallback.

## Project map

```text
src/
  main.tsx                       React mount and global styles
  app/                           Providers, routes and shell composition
    layout/                      Application-wide chrome
  features/
    auth/                        Session provider, login, route guard
    chat/                        Conversations, messages, meal plans, SSE
    purchases/                   History, exact-revision review and decisions
      api/                       Typed endpoint calls
      components/                Props-driven feature UI
      hooks/                     State, async actions and effects
      model/                     Purchase status derivation
      pages/                     Routed screen composition
  shared/
    api/                         Fetch transport, schema and type aliases
    components/                  Cross-feature UI
    hooks/                       Cross-feature hooks
    lib/                         Formatting
  styles/                        Tailwind theme and layered legacy CSS
e2e/                             Playwright behavior regressions
docs/                            Architecture, development and testing
AGENTS.md                        Instructions for coding agents
```

Features create only the subfolders they use. Start with the
[architecture](docs/architecture.md), [development guide](docs/development.md)
and [testing guide](docs/testing.md). Agents should read [AGENTS.md](AGENTS.md).

## Commands

Run these inside `frontend/`, or append `--prefix frontend` from the root.

| Command                    | Purpose                                                           |
| -------------------------- | ----------------------------------------------------------------- |
| `npm run dev`              | Vite with the backend API proxy                                   |
| `npm run check`            | ESLint, formatting check, TypeScript and production build         |
| `npm run lint`             | TypeScript/React rules and dependency boundaries                  |
| `npm run format`           | Format maintained source, config and docs                         |
| `npm run typecheck`        | Strict TypeScript without building assets                         |
| `npm run build`            | Lint, formatting, TypeScript and Vite output in `dist/`           |
| `npm run preview`          | Preview `dist/`; API requests still require backend hosting/proxy |
| `npm test`                 | UI regressions; live integration specs skip by default            |
| `npm run test:integration` | Opt in to backend/database browser checks                         |

First-time browser setup: `npm exec --prefix frontend -- playwright install chromium`.
The default UI tests start Vite automatically and intercept API calls. They
need no backend, database or private credentials.

## Refresh API types

From the repo root:

```sh
uv run python scripts/export_schema.py
npm run types --prefix frontend
npm run check --prefix frontend
```

Commit `frontend/openapi.json` and `src/shared/api/schema.ts` together when the
backend contract changes. `shared/api/types.ts` provides readable aliases;
`schema.ts` is generated and excluded from lint/format rewriting.

## Design and prototype reference

Use `../ui/DESIGN.md` plus the desktop/mobile references in `../ui/`.
`src/styles/theme.css` reuses PR #107's tokens and fonts, without preflight.
Legacy CSS is in a lower cascade layer, so utilities can override it as screens
migrate. API behavior and existing routes are retained by this structural pass;
new Home/Request layouts are subsequent visual work.

`prototypes/chat-ui/` is a standalone fake-data reference, excluded from this
package's lint, TypeScript and formatting checks. It is not the production
entry point. Coordinate designer-track integration against issue #59 and
PR #102; reuse suitable presentational work without importing the fake store.
