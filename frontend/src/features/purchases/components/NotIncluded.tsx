import {
  notIncludedItems,
  notIncludedReason,
  type DraftCart,
} from "../model/cart";
import { CART_COPY } from "../model/cartCopy";

/** The cart items that will not be ordered (no product or no quantity), with a plain warning. */
export function NotIncluded({ cart }: { cart: DraftCart | null }) {
  const left = notIncludedItems(cart);
  if (left.length === 0) return null;
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
        {left.map((item, index) => (
          <li key={index}>
            {item.name} · {notIncludedReason(item)}
          </li>
        ))}
      </ul>
    </section>
  );
}
