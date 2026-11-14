# Frontend architecture

## Runtime and build

`index.html` loads `src/main.tsx`, which mounts `app/App.tsx` in StrictMode and
loads `styles/theme.css`. `AuthProvider` restores the buyer session before the
app renders its shell and routes. React Router handles navigation. The frontend container
serves `dist/` and routes API requests to FastAPI. No Node server runs
in production; Vite is a development/build tool.

```mermaid
flowchart TD
  Entry[main.tsx] --> App[app: providers, shell, routes]
  App --> Auth[auth: session and login]
  App --> Chat[chat: pages, components, hooks]
  App --> Purchases[purchases: pages, components, hooks]
  Chat --> ChatAPI[chat/api]
  Purchases --> PurchaseAPI[purchases/api]
  Auth --> SessionAPI[auth/api]
  ChatAPI --> Transport[shared/api/client.ts]
  PurchaseAPI --> Transport
  SessionAPI --> Transport
  Transport --> Backend[Authenticated FastAPI /api]
```

Each feature's API module uses generated schema types. The chat API additionally
opens native EventSource connections; the chat hook owns their lifetime.
Shared modules do not import features or application composition. Features may
use a specific module from another feature when the dependency is explicit:
chat composes purchases’ Overview controller and status derivation; Home reuses
the accepted-order hook.

## Responsibilities

| Location                 | Owns                                                             | Does not own                         |
| ------------------------ | ---------------------------------------------------------------- | ------------------------------------ |
| `app/`                   | Providers, route table, shell                                    | Endpoint details, purchase decisions |
| `features/*/pages/`      | Route params and screen composition                              | Raw fetch calls                      |
| `features/*/components/` | Typed props, rendering and callbacks                             | Server state orchestration           |
| `features/*/hooks/`      | Loading/error states, actions, effects and recovery              | HTTP transport implementation        |
| `features/*/api/`        | Endpoint paths, typed request/response payloads and CSRF headers | React state and rendering            |
| `features/*/model/`      | Pure domain derivation                                           | Network effects                      |
| `shared/api/`            | Cookie-aware transport, generated schema, aliases                | Feature workflow decisions           |
| `shared/components/`     | Reused UI such as badges/errors                                  | Feature-specific controllers         |
| `styles/`                | Tokens, cascade order, legacy screen rules                       | Data or authorization                |

Keep local UI state local. Session state uses React context; server snapshots
and async actions remain in feature hooks. No global store or query library is
introduced for this refactor. Backend state remains authoritative.

## Route map

| URL                              | Component                                    | Authentication                                       |
| -------------------------------- | -------------------------------------------- | ---------------------------------------------------- |
| `/login`                         | `auth/pages/LoginPage`                       | Public; signed-in buyers return to their destination |
| `/`                              | `home/pages/HomePage`                        | Required                                             |
| `/request`                       | `chat/pages/ChatPage`                        | Required                                             |
| `/conversations/:conversationId` | `chat/pages/ChatPage`                        | Required                                             |
| `/schedules`                     | `schedules/pages/SchedulesPage`              | Required                                             |
| `/schedules/new`                 | `schedules/pages/ScheduleCreatePage`         | Required                                             |
| `/schedules/:scheduleId`         | `schedules/pages/ScheduleDetailPage`         | Required                                             |
| `/schedules/:scheduleId/edit`    | `schedules/pages/ScheduleEditPage`           | Required                                             |
| `/purchases`                     | `purchases/pages/PurchasesPage`              | Required                                             |
| `/purchases/:proposalId`         | `purchases/pages/PurchasesPage`              | Required                                             |
| `/approvals/:approvalId`         | Same detail page, historical approval lookup | Required                                             |
| `/approvals`                     | Redirect to `/purchases`                     | Destination requires sign-in                         |
| Other paths                      | Not-found view                               | Public                                               |

`RequireAuth` preserves the requested path through login. The route table is in
`app/AppRoutes.tsx`. Home, Request and Past Orders render inside `app/layout/AppShell`: a fixed
desktop sidebar with collapsible conversation navigation and a mobile menu.
Past Orders lists `GET /api/orders` (scheduled, pending, placed, cancelled rows); the Schedule
item opens the standing orders (see `docs/scheduler-ui.md`). Accepted-order deep links expand their receipt in Past Orders. Unplaced
purchase links retain a complete review with the shared Overview controls;
historical approval links retain the original revision.

## Important flows

### Session

`AuthProvider` calls `getSession()` on mount. A 401 represents signed out;
other bootstrap failures display an error. Login saves the returned session.
Logout uses its CSRF token and clears the session after success. Feature hooks
clear authentication on a 401; the route guard then sends the buyer to login.

### Conversation

`useChat(conversationId)` loads the sidebar and active snapshot. It retains
pagination, visible-tab refresh, SSE events, expiry and reconnect messaging.
Changing routes or unmounting closes the active event stream. Persisted backend
snapshots drive updates; the browser does not invent assistant results.

A stable creation key protects conversation creation. Pending message text/key
are stored in buyer/conversation-scoped session storage before sending. Retries
reuse that key, and server `retry_message` data can restore unfinished requests
on another browser. Active-route refs prevent old successful responses from
replacing the currently selected conversation.

### Purchase review

`useAcceptedOrders()` reads enough API pages to fill accepted orders, and owns
visible-tab refresh and pagination. Pending purchases stay in their conversations.
`usePurchaseDetail()` loads either a current proposal or the exact historical
approval. `PurchaseSheet` renders evidence and quantities;
`OverviewPanel` renders checks, closed states, receipts and explicit
confirm/reject callbacks through `PurchaseDecisionPanel`. In Request it is a
right column on desktop and an expandable bottom drawer below 1024px. Detailed
quantities, evidence and history remain accessible in its disclosure.

`confirmPurchase()` sends the exact proposal/revision and the existing
buyer-specific stable retry key with CSRF. The hook reloads server state after
confirmation. Revised terms display a notice and require another explicit
click. Text messages never authorize purchases. UI eligibility is advisory;
the backend enforces current identity, policy, revision and idempotency.
Accepted orders remain labelled as mock, without supplier checkout/reservation.

## Styling and generated code

Global CSS enters through `main.tsx` only. `styles/theme.css` contains the
#102 design tokens, Tailwind preflight/utilities, focus and reduced-motion rules;
the legacy stylesheet is removed. Shared disabled controls expose unavailable
design affordances. Static schedule/hub/account-manager examples are labelled
placeholders; actual account, conversation, basket and receipt data use the API.
The prototype store, fake authentication and scenario switcher are not runtime dependencies.

Python models → `scripts/export_schema.py` → `frontend/openapi.json` →
`npm run types` → `shared/api/schema.ts`. Never edit generated schema output.
Readable aliases live in `shared/api/types.ts`; endpoint wrappers belong to the
feature API modules. No provider or supplier credentials belong in this app.
