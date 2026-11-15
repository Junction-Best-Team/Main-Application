# Quantity controls and the zero ghost line on the cart card

Where: the lines of the prepared basket in the Overview (`OverviewPanel` -> `CartLines`). Specs: `frontend/e2e/cart-quantity.spec.ts`
(mocked API, typed fixtures from the generated contract in `e2e/support/cartFixtures.ts`, paused page clock). Code:
`components/{CartLines,QuantityControl,GhostLine}.tsx`, `hooks/useCartEdit.ts`, `model/cartEdit.ts` (numbers and sentences), `api/cartApi.ts`.

- **When there are controls:** the card is in a chat (`conversationId`), the purchase can still be confirmed (`flow.canConfirm`, so none after an
  order) and the conversation carries `cart_editable` / `cart_edit_reason`. With `cart_editable: true` the controls are live; with `false` and a
  reason they are disabled and the reason is shown (`data-testid="cart-edit-reason"`, also the inputs' description); with no reason (older
  conversations) the lines stay plain. While the assistant works (`conversation.busy`) they are disabled with "The assistant is still working on your request."
- **A control:** number input labelled `Quantity of <product>` (min 0, max 100000, whole packs) with buttons `Decrease quantity of <product>` and
  `Increase quantity of <product>`. Arrow keys change the number, Enter saves at once. An empty or invalid text is not sent
  (`Enter a whole number from 0 to 100000.`) and goes back to the server's number when the input loses focus.
- **Saving:** about 600 ms after the last key, one `PUT /api/conversations/{id}/cart` `{request_id, lines:[{product_id, sales_quantity}]}` with only the
  changed lines. One request at a time, typing is never blocked (what was typed meanwhile is sent next and is not overwritten by the older answer).
  `Updating…` (`data-testid="cart-updating"`) shows from the first key until the answer. The answer is the new basket: the card shows it, and the
  chat reloads (`onPrepared`). One request id per change, reused by `Try again`.
- **Errors:** the typed value stays (`aria-invalid`), the shared `ErrorMessage` says why and `Try again` re-sends the same request. The server's own
  sentence is shown for `ITEM_NOT_IN_CART`, `EMPTY_CART`, `RECIPE_BASKET_LOCKED`, `CART_QUANTITY_UNKNOWN`, `CONVERSATION_BUSY`, `BASKET_ALREADY_ORDERED`;
  `IDEMPOTENCY_CONFLICT` says "That change was already sent with other settings. Change the number again."; anything else "The quantity could not be saved. Try again."
- **The ghost:** when the server's answer no longer has a line the customer set to 0, the card keeps a client-side copy (name, unit, last quantity)
  at its old place: `data-testid="ghost-line"`, greyed (`opacity-50`), `was 4 BAG`, a button `Put <product> back`. A click, or typing a number above 0,
  puts it back (a click sends 1 at once, typing is debounced). After 15 seconds from the answer it fades (`data-state="fading"`, CSS opacity transition;
  with `prefers-reduced-motion` it is removed at once) and the polite live note (`data-testid="cart-live-note"`) says `Removed <product>`. A refusal
  (for example `EMPTY_CART`, the last line) leaves the line as it is with its typed 0; there is no ghost because the server still has the line.
  The line stays in the server's cart; asking the assistant brings it back.

## What the basket leaves out, and a changed cart

- `cart_not_included` (GET conversation, from the backend, computed on every read) lists what the current basket leaves out: items without a product
  (`no product yet`), without a quantity (`quantity needed`) and lines the customer set to 0 (`removed by you`). The prepared card shows them in the
  "Not included" block (`components/CartNotIncluded.tsx`) with "These items will not be ordered."; an item still on screen as a ghost is not listed
  twice. An older server without the field keeps the earlier behaviour.
- A 409 `CART_CHANGED` (the cart changed while an edit was being prepared) says: "Your cart changed while this number was being saved. Check the
  numbers and try again." The typed number stays and `Try again` re-sends the same request.
