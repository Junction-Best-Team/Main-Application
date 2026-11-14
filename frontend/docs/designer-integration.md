# Designer #102 integration

Reference: [PR #102](https://github.com/Junction-Best-Team/Main-Application/pull/102)
at `5f550d2`. The complete customer UI is adapted into production folders.

| Reference                                                                            | Production owner                                                                      |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| AppShell: desktop sidebar, mobile menu, account/header and collapsible conversations | `app/layout/AppShell` composes `chat/hooks/useConversationNavigation` and auth        |
| NoticeBar, icons, disabled controls, wordmark                                        | `shared/components/`                                                                  |
| Home: restock banner, schedule examples, recent accepted orders                      | `home/pages/HomePage`, `purchases/hooks/useAcceptedOrders`                            |
| Request: context header, thread, SKU cards, composer                                 | `chat/pages/` and `chat/components/`                                                  |
| Overview: right column, mobile drawer, totals, actions, receipt/closed states        | `purchases/components/OverviewPanel`, `StagedOverview`, `PurchaseDecisionPanel`       |
| Accepted-only Past Orders, pagination and expandable/deep-linked rows                | `purchases/pages/PurchasesPage`, `components/PurchaseList`, `hooks/useAcceptedOrders` |
| Login                                                                                | `auth/pages/LoginPage`, existing session API/provider                                 |
| Purchasing settings                                                                  | `settings/` feature, real Account Settings links in desktop sidebar and mobile menu   |
| Tokens, fonts, preflight; old stylesheet removed                                     | `styles/theme.css`, `index.html`                                                      |

Actual account/conversation/purchase data use existing API modules and generated
schema types. Confirmation retains CSRF, exact revision, stable retry keys and a
second explicit click after revised terms. Detailed quantities, policy checks,
evidence and history remain available. Old approval URLs retain their historical
revision; unplaced purchase URLs retain a complete review fallback. The Overview
drawer also covers tablet widths where the desktop sidebar leaves too little room.

Schedule/hub/account-manager examples and unavailable controls are labelled
placeholders. Prototype fake authentication, store, scenario switcher/DemoBar and
fixtures are development harnesses and are not shipped in production.
