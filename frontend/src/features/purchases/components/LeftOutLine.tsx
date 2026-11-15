import type { components } from "../../../shared/api/schema";
import { displayNames } from "../model/cardState";
import { CART_COPY } from "../model/cartCopy";

export type CartNotIncludedItem = components["schemas"]["CartNotIncluded"];

const reasonText = (item: CartNotIncludedItem) =>
  item.reason === "no_product"
    ? CART_COPY.noProduct
    : item.reason === "no_quantity"
      ? CART_COPY.noQuantity
      : CART_COPY.removedByYou;

/**
 * What the prepared basket leaves out, as one muted line (`cart_not_included` of the conversation):
 * items without a product, without a quantity, or removed by the customer. An item still on screen
 * as a ghost line is not listed twice.
 */
export function LeftOutLine({
  items,
  hideNames = [],
}: {
  items: CartNotIncludedItem[];
  hideNames?: string[];
}) {
  const shown = items.filter((item) => !hideNames.includes(item.name));
  if (shown.length === 0) return null;
  const names = displayNames(shown.map((item) => item.name));
  return (
    <p
      data-testid="card-left-out"
      className="m-0 text-label-sm text-on-surface-variant"
    >
      {CART_COPY.leftOut}:{" "}
      {shown.map((item, i) => `${names[i]} (${reasonText(item)})`).join(", ")}
    </p>
  );
}
