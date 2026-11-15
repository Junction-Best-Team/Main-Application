# Cart preparation and review

Cart preparation uses live supplier price and availability. Order acceptance is a persistent mock, with no supplier order or reservation. The customer must explicitly confirm the exact proposal revision before commitment.

**Routes and code:** `POST /api/conversations/{id}/prepare-from-cart` (`src/aimo/cart_purchase.py`) and `cart_purchase.auto_prepare`, called by `conversations.execute_turn`.

## What happens

- After a customer chat turn that left a changed cart (the turn's displayed plan), the server prepares the basket from it: the conversation's plan, every matched product read again from the catalog, the ordinary prepare path (fresh supplier price and stock, policy, ceiling, the customer's stated limits). Items without a product or quantity are left out and named in the reply ("Not included: ...").
- Skipped: nothing matched with a quantity (empty cart; the draft stays), the model prepared in that turn, nothing changed (the latest basket already holds these lines for these terms), a saved recipe plan with open ingredients. A failure is logged (`cart.auto_prepare_failed`) and never fails the turn.
- **Date and destination:** from the conversation's latest basket (the model's or the cart's); else tomorrow (Helsinki) and the first destination of the buyer's policy. The card's date and destination fields call the route again.
- **One open basket:** in the same database transaction that creates a cart or chat basket, every other unconfirmed basket of that conversation is cancelled (reason `customer_revised`, audit event `request_cancelled`); a basket with an order is never touched. A confirm of a cancelled basket gets `409 REQUEST_REVISED` ("The basket was revised. Review the new basket and confirm that one.") and nothing is ordered; commit rechecks the same. Both run under the buyer lock, so a racing confirm either places the order first (the old basket stays) or is refused.
- **Next turn:** the latest stored plan is restored (matched products verified again) even when a basket exists, so the assistant can edit the cart; a restored plan the model does not change is not shown again, so it makes no new basket.
- `CART_AUTO_PREPARE=false` switches the automatic part off (the route stays).

## Not the same as a chat basket
A server-originated prepare does not run the model-level semantic check of the prepare tool call (destination, date, budget and items match what the customer said). All fixed rules still apply. The date may be the default (tomorrow) if the customer named another day only in chat and the model did not prepare; the panel shows it and the date field changes it.

## Request readiness and requirements

An exploring request or one missing material meal/quantity facts does not prepare a
basket. With guardrails enforced, preparation requires the current turn's reviewed
`record_request` snapshot. Its budget, dietary/allergen, origin and unsupported
requirements apply to background preparation, manual cart preparation and agent tools;
none of these paths may loosen them. A supplier/preparation failure keeps the draft
and adds one brief retry notice. See [chat purchasing](chat-purchasing.md).

## Supplier calls
One prepare = two sequential supplier requests (price and availability, up to 100 product ids each) plus retries; made once per changed turn, never on read or reload.

## Saved recipe plans
The first prepare works. The plan is then locked (`RECIPE_PLAN_LOCKED`), so edits need a new request under the current saved-recipe edit restriction. The proposal's `recipe_basis` is `saved_recipe` for such a basket.

## Number edits on the card (PUT /api/conversations/{id}/cart)
Body `{request_id, lines:[{product_id, sales_quantity}]}`: whole sales units (packs) of products that are already in the stored cart (`ITEM_NOT_IN_CART` otherwise). The server converts packs to the plan's unit from catalog evidence, stores the edited plan as the newest assistant message together with a customer line ("I changed the cart on the card: ..."), prepares the basket again (older open basket cancelled atomically) and returns `{proposal, not_included}`. 0 keeps the product in the plan at amount "0" (left out of the basket, listed as `removed`); a value above 0 brings it back. The assistant sees the customer line and the stored plan with the new amounts, and is told never to undo a customer edit; `publish_meal_plan` accepts a carried-through "0" and `prepare_order` skips it. Saved-recipe carts: `422 RECIPE_BASKET_LOCKED` under the current saved-recipe edit restriction. `GET conversation` has `cart_editable` and `cart_edit_reason`.

## After an order
When the conversation's current cart (its latest stored plan) already has an order, `prepare-from-cart` and `PUT /cart` return `409 BASKET_ALREADY_ORDERED` (details.order_id), the automatic prepare does nothing for that plan, and `cart_editable` is false with "This order was already placed." A new plan (a new customer request) starts a new cart. The original press can still be replayed and returns its basket.

## Items left out, after a reload (`cart_not_included`)
`GET /api/conversations/{id}` carries `cart_not_included: [{name, amount, unit, reason: no_product | no_quantity | removed}]`: what the CURRENT basket leaves out, computed on every read from the latest stored plan (nothing is stored separately, no migration). It is empty without an open basket (none yet, cancelled, or with an order), when a newer plan was stored after the basket, for a saved recipe cart (it must be fully matched) and for an unreadable plan. The route and the PUT still return the same list in their answers.

## Customer card

The chat card shows an empty draft, a partially matched plan or the newest
non-cancelled proposal. Items without a product/quantity appear under “Not included”
and cannot be ordered. The confirm button stays disabled while the assistant works
or the proposal is blocked. It prepares an unprepared cart through
`POST /api/conversations/{id}/prepare-from-cart`; a prepared proposal uses
`POST /api/purchases/{id}/confirm` with its exact revision and stable retry key.
Changed terms are shown for another explicit confirmation.

Prepared proposals have Items, Delivery, Details and Checks tabs. Inactive panels
stay mounted so edits and retry state survive switching tabs. The tab returns to
Items on an edit, error or new basket. The footer keeps the total, VAT breakdown,
blocker, errors and confirmation action visible; blockers also mark the Checks tab.
Details and the full review show persisted evidence and policy state.

Delivery edits prepare again. Quantity edits use the server's `cart_editable` and
`cart_edit_reason`; see [quantity controls](cart-quantity.md) for debouncing, retry
and the temporary removed-line display. Ordered cards have no confirmation or
editing controls and retain receipt access. Mobile cards stay in the page flow.

Implementation lives in `frontend/src/features/purchases/`; API types come from
the generated schema. `frontend/e2e/cart-purchase.spec.ts`, `cart-quantity.spec.ts`
and `cart-tabs.spec.ts` cover the browser with authored route fixtures. Backend
coverage is in `tests/test_cart_purchase.py`; neither fixture suite proves live
supplier eligibility.
