# The cart is always the exact basket (Q-123d)

Mocks only: nothing here orders anything. The customer's Confirm purchase press on the exact revision is still the only thing that commits.

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

## Supplier calls
One prepare = two sequential supplier requests (price and availability, up to 100 product ids each) plus retries; made once per changed turn, never on read or reload.

## Saved recipe plans
The first prepare works. The plan is then locked (`RECIPE_PLAN_LOCKED`), so edits need a new request until the owner decides Q-126. The proposal's `recipe_basis` is `saved_recipe` for such a basket.
