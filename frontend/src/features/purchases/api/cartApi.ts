import { api } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

// The generated contract (a7, p3/cart-purchase-button): the customer's own cart routes.
// Policy problems (past date, foreign destination, ceiling, stock, price) are not errors: they come
// back as a normal proposal with `policy_outcome` and `reasons`.
export type PrepareFromCartBody = components["schemas"]["CartPurchaseRequest"];
export type NotIncluded = components["schemas"]["CartNotIncluded"];
export type PrepareFromCartResult =
  components["schemas"]["CartPurchaseResponse"];
export const prepareFromCart = (
  csrfToken: string,
  conversationId: string,
  body: PrepareFromCartBody,
) =>
  api<PrepareFromCartResult>(
    `/api/conversations/${conversationId}/prepare-from-cart`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(body),
    },
  );

// PUT /api/conversations/{id}/cart: the customer edits the pack count of products already in the cart.
export type CartEditBody = components["schemas"]["CartEditRequest"];
export type CartEditResult = components["schemas"]["CartPurchaseResponse"];
export const editCart = (
  csrfToken: string,
  conversationId: string,
  body: CartEditBody,
) =>
  api<CartEditResult>(`/api/conversations/${conversationId}/cart`, {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });

// POST /api/conversations/{id}/refresh-basket {request_id}: prepares an EXPIRED basket again from the stored
// cart (fresh supplier price and stock, same date, destination and pack counts). Never confirms or orders.
// 409 BASKET_NOT_EXPIRED when the latest basket is still valid, 422 NO_BASKET_TO_REFRESH without a basket.
export type CartRefreshBody = components["schemas"]["CartRefreshRequest"];
export const refreshBasket = (
  csrfToken: string,
  conversationId: string,
  body: CartRefreshBody,
) =>
  api<PrepareFromCartResult>(
    `/api/conversations/${conversationId}/refresh-basket`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(body),
    },
  );
