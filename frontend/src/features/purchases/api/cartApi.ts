import { api } from "../../../shared/api/client";
import type { Proposal } from "../../../shared/api/types";

// PROPOSED CONTRACT (from the backend owner, branch p3/cart-purchase-button, not merged): the route is not
// in the generated schema yet, so the types are written by hand. Replace them with the generated ones
// when it lands. Policy problems (past date, foreign destination, ceiling, stock, price) are not errors:
// they come back as a normal proposal with `policy_outcome` and `reasons`.
export type PrepareFromCartBody = {
  delivery_date: string; // YYYY-MM-DD
  destination: string; // 1..120 characters
  /** One per button press, reused on a retry of the same press (8..120 characters). */
  request_id: string;
};
export type NotIncluded = {
  name: string;
  amount: string | null;
  unit: string;
  reason: "no_product" | "no_quantity";
};
export type PrepareFromCartResult = {
  proposal: Proposal;
  not_included: NotIncluded[];
};
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
