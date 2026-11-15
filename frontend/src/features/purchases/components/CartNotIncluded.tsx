import type { components } from "../../../shared/api/schema";
import { CART_COPY } from "../model/cartCopy";

export type CartNotIncludedItem = components["schemas"]["CartNotIncluded"];

const reasonText = (item: CartNotIncludedItem) =>
  item.reason === "no_product"
    ? CART_COPY.noProduct
    : item.reason === "no_quantity"
      ? CART_COPY.noQuantity
      : CART_COPY.removedByYou;

/**
 * What the prepared basket leaves out, as the server reports it on every read (`cart_not_included`):
 * items without a product, without a quantity, or removed by the customer on the card. Plain text; the
 * items still on screen as a ghost line are not listed twice.
 */
export function CartNotIncludedList({
  items,
  hideNames = [],
}: {
  items: CartNotIncludedItem[];
  hideNames?: string[];
}) {
  const shown = items.filter((item) => !hideNames.includes(item.name));
  if (shown.length === 0) return null;
  return (
    <section
      aria-label={CART_COPY.notIncludedHeading}
      className="rounded-lg bg-amber-50 p-space-sm text-body-sm text-amber-950"
    >
      <p className="m-0 font-label text-label-md font-bold">
        {CART_COPY.notIncludedHeading}
      </p>
      <p className="m-0">{CART_COPY.notIncludedWarning}</p>
      <ul className="m-0 list-none p-0">
        {shown.map((item, index) => (
          <li key={`${item.name}-${index}`}>
            {item.name} · {reasonText(item)}
          </li>
        ))}
      </ul>
    </section>
  );
}
