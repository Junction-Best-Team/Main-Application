import { useState } from "react";
import type { Proposal } from "../../../shared/api/types";
import { currency, dateTime } from "../../../shared/lib/format";
import { useCartOpen } from "../hooks/useCartOpen";
import { CartShell } from "./CartShell";
import { useDestinations } from "../hooks/useDestinations";
import { usePrepareFromCart } from "../hooks/usePrepareFromCart";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { NotIncluded } from "./NotIncluded";
import { CardLogCopy } from "./CardLogCopy";
import { useCardLog } from "../model/cardLog";
import {
  cartBlockedReason,
  tomorrowInHelsinki,
  includedItems,
  type DraftCart,
} from "../model/cart";
import { CART_COPY } from "../model/cartCopy";

const field =
  "rounded-lg border border-outline-variant bg-surface-pure px-space-sm py-2 font-body text-body-sm text-on-surface";

/**
 * The card on the right of every chat. With no items it is empty and its purchase button is greyed
 * out with a reason; as soon as one item has a product and a quantity the button is green and
 * prepares the purchase from the cart (the final commit is the existing purchase button).
 */
export function DraftCartPanel({
  cart,
  conversationId,
  working = false,
  onPrepared,
}: {
  cart: DraftCart | null;
  conversationId?: string;
  /** The assistant is busy on this conversation: the purchase cannot be prepared meanwhile. */
  working?: boolean;
  onPrepared?: (proposal: Proposal) => void;
}) {
  const [open, toggleOpen] = useCartOpen("draft");
  const items = cart?.items ?? [];
  const destinations = useDestinations();
  const earliest = tomorrowInHelsinki();
  const [pickedDate, setPickedDate] = useState<string | null>(null);
  const [pickedDestination, setPickedDestination] = useState<string | null>(
    null,
  );
  const date = pickedDate ?? earliest;
  const destination =
    pickedDestination && destinations.includes(pickedDestination)
      ? pickedDestination
      : (destinations[0] ?? CART_COPY.defaultDestination);
  const reason = cartBlockedReason(cart, date, earliest, working);
  const { prepare, busy, error, errorDebug } = usePrepareFromCart(
    conversationId,
    onPrepared,
  );
  const reasonId = "cart-confirm-reason";
  // Diagnosis (debug mode only): what decides the purchase button.
  useCardLog({
    kind: "button",
    component: "draft",
    enabled: !reason && !busy,
    reason:
      !cart || items.length === 0
        ? "empty cart"
        : working
          ? "assistant working"
          : includedItems(cart).length === 0
            ? "nothing ready"
            : !date || date < earliest
              ? "date too early"
              : busy
                ? "preparing"
                : "none",
  });
  function press() {
    if (!cart || reason || busy) return;
    void prepare({ date, destination }, [
      cart.turn_id,
      includedItems(cart).map((i) => [i.product_id, i.amount]),
    ]);
  }
  return (
    <CartShell
      label="Your order"
      title="Your order"
      open={open}
      onToggle={toggleOpen}
      headerExtra={<CardLogCopy />}
      count={items.length || undefined}
    >
      {(!cart || working) && (
        <p role="status" className="my-space-sm text-body-sm text-secondary">
          {cart ? CART_COPY.preparingOrder : CART_COPY.empty}
        </p>
      )}
      {cart && (
        <div className={`${open ? "flex" : "hidden"} flex-col gap-space-sm`}>
          <h3 className="font-label text-label-md font-bold text-primary">
            {cart.title}
          </h3>
          <ul className="m-0 flex list-none flex-col gap-space-sm p-0">
            {items.map((item, index) => (
              <li
                key={index}
                className="border-b border-border-subtle pb-space-sm text-body-sm"
              >
                <div className="flex justify-between gap-space-sm">
                  <span className="min-w-0 break-words font-bold text-primary">
                    {item.name}
                  </span>
                  <span className="shrink-0 font-mono text-secondary">
                    {item.amount ?? "Quantity needed"}{" "}
                    {item.amount ? item.unit : ""}
                  </span>
                </div>
                <p className="mt-1 break-words text-secondary">
                  {item.matched
                    ? (item.product_name ?? item.product_id)
                    : "Product to match"}
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
                ) : (
                  <p className="mt-1 text-secondary">Price not checked</p>
                )}
              </li>
            ))}
          </ul>
          <NotIncluded cart={cart} />
          {includedItems(cart).length > 0 && (
            <div className="flex flex-col gap-space-sm">
              <label className="flex flex-col gap-1 font-label text-label-md text-primary">
                {CART_COPY.dateLabel}
                <input
                  type="date"
                  value={date}
                  min={earliest}
                  onChange={(e) => setPickedDate(e.target.value)}
                  className={field}
                />
              </label>
              {destinations.length > 1 ? (
                <label className="flex flex-col gap-1 font-label text-label-md text-primary">
                  {CART_COPY.destinationLabel}
                  <select
                    value={destination}
                    onChange={(e) => setPickedDestination(e.target.value)}
                    className={field}
                  >
                    {destinations.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                destination && (
                  <p className="m-0 font-label text-label-md text-primary">
                    {CART_COPY.destinationLabel}:{" "}
                    <span className="font-body">{destination}</span>
                  </p>
                )
              )}
            </div>
          )}
        </div>
      )}
      <div className="mt-space-sm flex flex-col gap-space-xs">
        <ErrorMessage message={error} debug={errorDebug} />
        <button
          type="button"
          disabled={Boolean(reason) || busy}
          aria-describedby={reason ? reasonId : undefined}
          onClick={press}
          className="cursor-pointer rounded-lg border-0 bg-green-700 px-space-md py-3 font-label text-label-lg font-bold text-white hover:bg-green-800 disabled:cursor-not-allowed disabled:bg-surface-container-high disabled:text-on-surface-variant"
        >
          {busy ? CART_COPY.preparing : CART_COPY.button}
        </button>
        {reason && (
          <p
            id={reasonId}
            className="m-0 text-label-sm text-on-surface-variant"
          >
            {reason}
          </p>
        )}
      </div>
    </CartShell>
  );
}
