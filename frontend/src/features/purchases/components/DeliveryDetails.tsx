import { useState } from "react";
import type { Proposal } from "../../../shared/api/types";
import { useDestinations } from "../hooks/useDestinations";
import type { usePrepareFromCart } from "../hooks/usePrepareFromCart";
import { formatDate } from "../../schedules/model/scheduleStatus";
import { tomorrowInHelsinki, type DraftCart } from "../model/cart";
import { CART_COPY } from "../model/cartCopy";

const field =
  "rounded-lg border border-outline-variant bg-surface-pure px-space-sm py-2 font-body text-body-sm text-on-surface";

/**
 * The delivery date and destination of the prepared purchase. Changing either asks the server to
 * prepare the purchase again (prepare-from-cart), after which the card shows the new revision.
 */
export function DeliveryDetails({
  p,
  cart,
  working,
  prep,
}: {
  p: Proposal;
  cart: DraftCart | null;
  working: boolean;
  /** The prepare-from-cart state, kept by the card so its error shows in the pinned footer. */
  prep: ReturnType<typeof usePrepareFromCart>;
}) {
  const destinations = useDestinations();
  const options = destinations.includes(p.request.destination)
    ? destinations
    : [p.request.destination, ...destinations];
  const [date, setDate] = useState(p.request.delivery_date);
  const [destination, setDestination] = useState(p.request.destination);
  const { prepare, busy } = prep;
  const earliest = tomorrowInHelsinki();
  const changed =
    date !== p.request.delivery_date || destination !== p.request.destination;
  const tooEarly = !date || date < earliest;
  return (
    <div className="flex flex-col gap-space-sm border-t border-border-subtle pt-space-sm">
      <label className="flex flex-col gap-1 font-label text-label-md text-primary">
        {CART_COPY.dateLabel}
        <input
          type="date"
          value={date}
          min={earliest}
          onChange={(e) => setDate(e.target.value)}
          className={field}
        />
      </label>
      {options.length > 1 ? (
        <label className="flex flex-col gap-1 font-label text-label-md text-primary">
          {CART_COPY.destinationLabel}
          <select
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            className={field}
          >
            {options.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="m-0 font-label text-label-md text-primary">
          {CART_COPY.destinationLabel}:{" "}
          <span className="font-body">{destination}</span>
        </p>
      )}
      {changed && (
        <>
          <button
            type="button"
            disabled={tooEarly || busy || working}
            onClick={() =>
              void prepare({ date, destination }, [
                cart?.turn_id,
                p.proposal_id,
              ])
            }
            className="cursor-pointer rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
          >
            {CART_COPY.updateDelivery}
          </button>
          {tooEarly && (
            <p className="m-0 text-label-sm text-on-surface-variant">
              {CART_COPY.dateReason(formatDate(earliest))}
            </p>
          )}
        </>
      )}
    </div>
  );
}
