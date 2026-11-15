import { useEffect, useRef, useState } from "react";
import type { Proposal } from "../../../shared/api/types";
import { useDestinations } from "../hooks/useDestinations";
import type { usePrepareFromCart } from "../hooks/usePrepareFromCart";
import { formatDate } from "../../schedules/model/scheduleStatus";
import { tomorrowInHelsinki, type DraftCart } from "../model/cart";
import { shortDate } from "../model/cardState";
import { CART_COPY } from "../model/cartCopy";

// The value looks like plain text; hover shows a subtle background, a click puts the cursor in it.
const inline =
  "w-full min-w-0 rounded-md border border-transparent bg-transparent px-1 py-0.5 font-body text-body-sm text-primary hover:bg-surface-container-low focus:border-outline-variant focus:bg-surface-container-low focus:outline-none disabled:cursor-not-allowed";

/**
 * The Delivery tab: a labelled list. Each value is edited in place, like the pack counts: click it, type,
 * and Enter or leaving the field saves (a destination is chosen from the buyer's list and saves at once).
 * Saving a date or a destination prepares the order again (prepare-from-cart, one request id per change,
 * its error in the footer). Read-only once the order is placed. The backend has only a date and a
 * destination name today: address, contact and note rows are drawn only when `extra` carries them.
 */
export function DeliveryPanel({
  p,
  cart,
  working,
  prep,
  canEdit,
  focusDate = 0,
  extra = [],
}: {
  p: Proposal;
  cart: DraftCart | null;
  working: boolean;
  prep: ReturnType<typeof usePrepareFromCart>;
  canEdit: boolean;
  /** Changes each time the date should take the keyboard focus (the Edit link above the tabs). */
  focusDate?: number;
  /** Further labelled rows (address, contact, note) when the data exists; empty today. */
  extra?: { label: string; value: string }[];
}) {
  const dateField = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusDate > 0) dateField.current?.focus();
  }, [focusDate]);
  const destinations = useDestinations();
  const options = destinations.includes(p.request.destination)
    ? destinations
    : [p.request.destination, ...destinations];
  const [date, setDate] = useState(p.request.delivery_date);
  const [destination, setDestination] = useState(p.request.destination);
  const earliest = tomorrowInHelsinki();
  const changed =
    date !== p.request.delivery_date || destination !== p.request.destination;
  const tooEarly = !date || date < earliest;
  const locked = !canEdit || working || prep.busy;
  function save(next: { date: string; destination: string }) {
    const differs =
      next.date !== p.request.delivery_date ||
      next.destination !== p.request.destination;
    if (!differs || !next.date || next.date < earliest || locked) return;
    void prep.prepare(next, [cart?.turn_id, p.proposal_id]);
  }
  const row = (label: string, value: React.ReactNode) => (
    <div key={label} className="contents">
      <dt className="m-0 self-center font-label text-label-md text-secondary">
        {label}
      </dt>
      <dd className="m-0 min-w-0 break-words">{value}</dd>
    </div>
  );
  return (
    <div className="flex flex-col gap-space-sm">
      <dl className="m-0 grid grid-cols-[auto_1fr] items-center gap-x-space-md gap-y-1 text-body-sm">
        {row(
          "Date",
          canEdit ? (
            <input
              ref={dateField}
              type="date"
              aria-label={CART_COPY.dateLabel}
              value={date}
              min={earliest}
              disabled={locked}
              onChange={(e) => setDate(e.target.value)}
              onBlur={() => save({ date, destination })}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  save({ date, destination });
                } else if (e.key === "Escape") setDate(p.request.delivery_date);
              }}
              className={inline}
            />
          ) : (
            `${shortDate(p.request.delivery_date)} ${p.request.delivery_date.slice(0, 4)}`
          ),
        )}
        {row(
          "Destination",
          canEdit && options.length > 1 ? (
            <select
              aria-label={CART_COPY.destinationLabel}
              value={destination}
              disabled={locked}
              onChange={(e) => {
                setDestination(e.target.value);
                save({ date, destination: e.target.value });
              }}
              className={inline}
            >
              {options.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          ) : (
            <span className="px-1">{p.request.destination}</span>
          ),
        )}
        {extra.filter((r) => r.value).map((r) => row(r.label, r.value))}
      </dl>
      {changed && tooEarly && (
        <p
          data-testid="delivery-hint"
          className="m-0 text-label-sm text-on-surface-variant"
        >
          {CART_COPY.dateReason(formatDate(earliest))}
        </p>
      )}
    </div>
  );
}
