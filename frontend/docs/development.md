# Changing the frontend

## Choose the right home

For an existing workflow, start in its feature. For example, chat layout lives
in `features/chat/components/` and `pages/`; message retries live in
`features/chat/hooks/useChat.ts`; endpoint changes live in `chat/api/chatApi.ts`.
Purchase status derivation lives in `purchases/model/purchaseStatus.ts`.

For a new feature, create its folder under `src/features/` and add only the
subfolders you need. Add the route in `app/AppRoutes.tsx`. Use `RequireAuth` for
buyer-only screens. Prefer named exports and direct module imports; avoid
large barrel files, generic service registries and parallel global stores.

## Add or extract a component

1. Keep the component in its feature unless multiple features need it.
2. Give it typed props for the data it renders and callbacks for user actions.
3. Keep loading/retry/network orchestration in the owning feature hook. Render
   loading, empty, error and closed states deliberately.
4. Keep DOM semantics, labels, keyboard focus and responsive behavior intact.
5. When extraction changes behavior, add a regression for the user's observable
   flow rather than the component's implementation details.

Shared UI currently contains `Badge` and `ErrorMessage`. There is no mandatory
wrapper around native buttons, inputs or links; introduce primitives only when
there is a repeated visual/behavioral contract to maintain.

## Add or change an API call

1. Change/confirm the Python contract with the backend owner.
2. Export OpenAPI and regenerate types using the [root development guide](../../docs/development.md#update-the-browser-api-contract).
3. Add the endpoint function in the owning feature's `api/` module. Use the
   shared `api<T>()` transport and generated input/output shapes.
4. Pass the session CSRF token for writes. Keep private provider keys on the
   server. Do not add a fixture fallback to production requests.
5. Handle success, loading, failure and session expiry in the feature hook.
6. Extend Playwright route fixtures to prove the intended user behavior.

The transport preserves same-origin cookies and backend error messages. It
throws `ApiError` with the HTTP status so feature hooks can distinguish session
expiry. Native EventSource is opened in `chat/api/chatApi.ts` and managed by
`useChat`; it does not use the JSON transport.

## Restyle a screen

Use `../../ui/DESIGN.md` and desktop/mobile references as the visual source.
Keep reusable tokens in `src/styles/theme.css`. Hanken Grotesk is the body and
heading face; Space Grotesk is for labels/data. These fonts and Material Symbols
are bundled from locked Fontsource packages by `src/main.tsx`; local dev and
production do not request Google Fonts. Distributed notices are in
`public/font-licenses/`. Pair lime actions with navy text.

Apply utilities to the extracted components and remove their obsolete rules
from base defaults in `theme.css`. Utilities occupy the last cascade layer. Keep global imports
at the entry point, retain visible focus and check both desktop and mobile.
The complete #102 screen layout now runs in production’s feature structure.
Home lives in `features/home`; conversation navigation stays in chat hooks;
Overview and accepted-order pagination stay in purchases. The app shell only
composes those features. Tailwind preflight is enabled and legacy CSS removed.
Check all screens at desktop and phone sizes when adjusting global defaults.
Disabled design controls and example schedules must remain visibly identified
as placeholders. Never import the prototype store, fixtures or API types.

## Tooling dependencies

Keep `package-lock.json` with dependency changes and verify using `npm ci`.
The scoped `@typescript-eslint/typescript-estree` override selects patched
`minimatch` 11 for the lint parser's glob matching, addressing
[GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249).
Recheck the upstream dependency before removing that override. It does not
affect the production browser bundle.

## Before handing off

Run `npm run check` and the relevant behavior suite. Explain which files own the
new behavior, which contracts changed, what ran, and any live dependency that
remains unverified. Root branch/PR rules still apply. Keep documentation focused
on how the code works; do not copy generated schema or maintain a second API
specification here.
