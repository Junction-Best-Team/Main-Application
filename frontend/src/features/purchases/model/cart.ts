import type { Conversation } from "../../../shared/api/types";
import { formatDate } from "../../schedules/model/scheduleStatus";
import { CART_COPY } from "./cartCopy";

export type DraftCart = NonNullable<Conversation["draft_cart"]>;
export type CartItem = DraftCart["items"][number];

/** An item is ordered only when it has a product and a quantity. */
export const isIncluded = (item: CartItem) =>
  Boolean(item.matched && item.product_id && item.amount);

export const includedItems = (cart: DraftCart | null) =>
  cart?.items.filter(isIncluded) ?? [];

export const notIncludedItems = (cart: DraftCart | null) =>
  cart?.items.filter((item) => !isIncluded(item)) ?? [];

/** Why an item is left out, in words. */
export function notIncludedReason(item: CartItem) {
  const noProduct = !item.matched || !item.product_id;
  const noQuantity = !item.amount;
  if (noProduct && noQuantity) return CART_COPY.noProductOrQuantity;
  return noProduct ? CART_COPY.noProduct : CART_COPY.noQuantity;
}

/** Tomorrow in Helsinki, as YYYY-MM-DD: the first delivery day offered (validity is checked per product when preparing). */
export const tomorrowInHelsinki = (now = Date.now()) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Helsinki" }).format(
    new Date(now + 86_400_000),
  );

/** Why the purchase button is greyed out, or null when it can be pressed. */
export function cartBlockedReason(
  cart: DraftCart | null,
  date: string,
  earliest: string,
  working = false,
): string | null {
  if (!cart || cart.items.length === 0) return CART_COPY.noItems;
  if (working) return CART_COPY.working;
  if (includedItems(cart).length === 0) return CART_COPY.nothingReady;
  if (!date || date < earliest)
    return CART_COPY.dateReason(formatDate(earliest));
  return null;
}
