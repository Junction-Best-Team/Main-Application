import { useState } from "react";
import type { Conversation } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { currency, dateTime } from "../../../shared/lib/format";

export function DraftCartPanel({
  cart,
}: {
  cart: NonNullable<Conversation["draft_cart"]>;
}) {
  const [open, setOpen] = useState(false);
  const matched = cart.items.filter((item) => item.matched).length;
  return (
    <aside
      aria-label="Draft cart"
      className="fixed inset-x-3 bottom-4 z-30 flex max-h-[70dvh] min-w-0 flex-col overflow-y-auto rounded-xl border border-border-subtle bg-surface-pure p-space-md shadow-level-3 lg:sticky lg:inset-x-auto lg:bottom-auto lg:top-0 lg:z-auto lg:max-h-full lg:w-80 lg:shrink-0 lg:shadow-sm xl:w-96"
    >
      <div className="flex items-center justify-between gap-space-sm border-b border-border-subtle pb-space-sm">
        <h2 className="m-0 font-headline text-headline-sm font-bold text-primary">
          Draft cart
        </h2>
        <button
          type="button"
          aria-label={open ? "Collapse draft cart" : "Expand draft cart"}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="flex h-9 w-9 items-center justify-center rounded-lg border-0 bg-transparent p-0 text-secondary lg:hidden"
        >
          <Icon name={open ? "keyboard_arrow_down" : "keyboard_arrow_up"} />
        </button>
      </div>
      <p role="status" className="my-space-sm text-body-sm text-secondary">
        {matched} of {cart.items.length} items matched
      </p>
      <div
        className={`${open ? "flex" : "hidden lg:flex"} flex-col gap-space-sm`}
      >
        <h3 className="font-label text-label-md font-bold text-primary">
          {cart.title}
        </h3>
        <ul className="m-0 flex list-none flex-col gap-space-sm p-0">
          {cart.items.map((item, index) => (
            <li
              key={index}
              className="border-b border-border-subtle pb-space-sm text-body-sm"
            >
              <div className="flex justify-between gap-space-sm">
                <span className="min-w-0 break-words font-bold text-primary">
                  {item.name}
                </span>
                <span className="shrink-0 font-mono text-secondary">
                  {item.amount ?? "Quantity needs verification"}{" "}
                  {item.amount ? item.unit : ""}
                </span>
              </div>
              <p className="mt-1 break-words text-secondary">
                {item.matched
                  ? (item.product_name ?? item.product_id)
                  : "No product selected yet"}
              </p>
              {item.price ? (
                <div className="mt-1 text-secondary">
                  <p>
                    {currency(item.price.gross, item.price.currency)} /{" "}
                    {item.price.sales_unit} incl. VAT
                  </p>
                  <p className="text-label-sm">
                    {item.price.mode === "fixture"
                      ? "Fixture price · invented demo data"
                      : "Supplier price"}
                    {" · "}Delivery {item.price.delivery_date}
                  </p>
                  <p className="text-label-sm">
                    Checked {dateTime(item.price.observed_at)}
                  </p>
                </div>
              ) : item.matched ? (
                <p className="mt-1 text-secondary">Price not checked</p>
              ) : null}
            </li>
          ))}
        </ul>
        <p className="m-0 rounded bg-secondary-container/40 p-2 text-body-sm text-primary">
          This is a recipe estimate. Products, pack sizes, availability and the
          full total need verification before purchase.
        </p>
      </div>
    </aside>
  );
}
