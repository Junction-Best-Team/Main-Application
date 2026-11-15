# The cart card and the Confirm purchase button (frontend, MOCK contract)

The right-hand card is always in a chat. Wording lives in one file, `frontend/src/features/purchases/model/cartCopy.ts`
(RECOMMENDED defaults while the owner's questions Q-123 to Q-125 are open).

- **Nothing to order**: an empty "Draft cart" card; "Confirm purchase" is greyed out and its reason is the
  accessible description ("Add items first").
- **Items in the cart, no purchase yet** (the first moment): green "Confirm purchase" once at least one item has a
  product and a quantity; greyed while the assistant works (`conversation.busy`), when nothing is ready, or when the
  delivery date is before tomorrow (Helsinki). Delivery date (tomorrow, editable) and destination (the buyer's policy
  destination, default `hotel-helsinki`) are on the card. Items without a product or quantity are listed under
  "Not included" with "These items will not be ordered." Pressing it calls `POST /api/conversations/{id}/prepare-from-cart`.
- **A purchase is prepared**: the card is the Overview with the exact lines and total. "Confirm purchase" (formerly
  "Approve & Push to Dispatch") commits that exact revision in one press (`POST /api/purchases/{id}/confirm`, unchanged).
  The delivery date and destination stay editable; "Update delivery details" (only after a change) prepares again, and the
  card shows the new revision. While a turn runs the card is dimmed (`aria-busy`) and the button greyed.
  A stale press comes back as `revised` and the existing sentence "Terms changed during verification. Review the new
  revision and confirm again." is shown with the new revision.
- **The routes use the generated contract** (a7, `p3/cart-purchase-button`): `src/features/purchases/api/cartApi.ts` has no hand-written
  types any more (`CartPurchaseRequest`, `CartPurchaseResponse`, `CartEditRequest` from `schema.ts`). One request id per press,
  reused on a retry (`hooks/usePrepareFromCart.ts`).
- **Pack counts** are edited on the card with number controls and a 15 second ghost for a line set to 0: see `docs/cart-quantity.md`.
- On a phone the empty/draft card sits below the chat in the page flow, never over the composer.

Specs: `frontend/e2e/cart-purchase.spec.ts` and `frontend/e2e/cart-quantity.spec.ts` (mocked API, local runs).

## Handoff (6c, end of session)

Done on `p3/cart-purchase-ui` (all with mocked specs in `frontend/e2e/cart-purchase.spec.ts`, local runs):
always-rendered card; empty/draft/purchase states; green one-press "Confirm purchase"; delivery date + destination
(`DeliveryDetails.tsx`, `hooks/usePrepareFromCart.ts`); "Not included" list (`NotIncluded.tsx`); default-open collapsible
card remembered in localStorage (`hooks/useCartOpen.ts`); newest non-cancelled basket is the card
(`StagedOverview.currentBasket`); after an order the card has no Confirm button and no date/destination controls
(they only render while `flow.canConfirm`).

Not done:

- **Quantity controls and the 15 s ghost line** (taken over by junction-b4 on `p3/cart-quantity-ui`). Hook in `OverviewPanel.tsx`
  at the lines list (`Items`), inside the block rendered only when `conversationId` is set (same place as `DeliveryDetails`);
  the proposed `PUT /api/conversations/{id}/cart` body is `{request_id, lines:[{product_id, sales_quantity}]}` (a7 may change it);
  disable the controls with `conversation.cart_editable` / `cart_edit_reason` when a7's fields land (not in the generated
  schema yet; read them as optional). The ghost is client-side state keyed by product id, kept 15 s.
- **Server reasons**: `cart_editable` false "This order was already placed." and 409 `BASKET_ALREADY_ORDERED` are not
  handled specially yet (the card already hides its controls once the purchase has an order); `REQUEST_REVISED` on confirm
  shows the server message through the existing error line and reloads the purchase (no dedicated spec yet).
- The receipt link on an ordered card exists only on `p3/flow-ui` ("View receipt", `OverviewPanel`); this branch has none.
- Merge order: after a7's backend (routes are a typed mock in `api/cartApi.ts`). Conflicts to expect with `p3/flow-ui` and
  `p3/debug-copy` in `OverviewPanel.tsx`, `StagedOverview.tsx`, `useChat.ts`, `ChatPage.tsx` (small).

## Tabs (layout D)

Once a purchase is prepared the card has four tabs, **Items | Delivery | Details | Checks** (`components/CardTabs.tsx`, `model/cardTabs.ts`), all
panels mounted (the inactive ones hidden) so typed numbers, ghost timers and request ids survive a tab switch. Items is the default; the tab goes
back to Items on any edit, any error and a new basket (new proposal id), never because a basket was only updated (`hooks/useCardTab.ts`, logged
as `kind: "tab"` in debug mode). The empty and the unprepared (draft) card have no tabs.

- **Pinned footer** (`components/CardFooter.tsx`), always under the tabs: `Total` with the amount, the status chip (only when the order is not
  ready) and the circular **i** on the right of the same row (`aria-label "VAT breakdown"`, `aria-expanded`, `aria-controls`; opens Excl. VAT,
  VAT n% and Total under the total; amounts and rate come from the proposal, none shown when the total is unresolved; closed by default, kept
  across tab switches and basket updates, closed by a new basket); then the one-line blocker or reason (`card-reason`, also the button's
  description), the status line, errors (with Try again for a failed edit) and the Confirm purchase button; Reject for an approver.
- **A blocker is never only under Checks**: the footer line ("Diced bacon: no pack size", "This order cannot be confirmed yet...", "This order
  expired...") and a badge on the Checks tab.
- **Delivery**: one line above the tabs ("Tue 17 Nov · hotel-helsinki", "Blocked · ..." or "Order placed · ..." in those states, with an Edit link
  that opens the tab and focuses the date) and the Delivery tab, a labelled list whose values are edited in place: click, type, Enter or leave the
  field saves (a destination is picked from the buyer's list); saving prepares the order again (prepare-from-cart, one request id, its error in the
  footer). Read-only once ordered. Address, contact and note rows exist only when the API carries them (it does not today).
- **Details** (`components/DetailsPanel.tsx`): rows with real data only: Order reference, Revision and when it was made, Prices valid until, Cut-off
  (when the lines carry it), Policy and approval status, the Allow substitutions switch (read-only), the sample notice, More (the full sheet) and
  Refresh status. **Checks** (`components/PurchaseChecks.tsx`): the purchasing checks with their codes and the approval status.
- **Items**: short product names (weights removed; the full name is the row's title and in More; two rows that would look alike keep their
  weights), the numbers with thin carets above and below that show on hover or keyboard focus (always faint on touch screens), one muted
  "Left out: ..." line (`cart_not_included`).
