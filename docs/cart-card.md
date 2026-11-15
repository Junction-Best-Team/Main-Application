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
