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
- **The route is a PROPOSED contract**, not in the generated schema yet: `frontend/src/features/purchases/api/cartApi.ts`
  has the hand-written types (request `delivery_date`, `destination`, `request_id`; answer `{proposal, not_included}`).
  Replace them with the generated ones when the backend lands (`npm run types`). One request id per press, reused on a
  retry (`hooks/usePrepareFromCart.ts`).
- On a phone the empty/draft card sits below the chat in the page flow, never over the composer.

Specs: `frontend/e2e/cart-purchase.spec.ts` (mocked API, local runs).

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
