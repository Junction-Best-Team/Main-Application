import { Link } from "react-router-dom";
import type { OrderListItem } from "../../../shared/api/types";
import { currency, dateTime } from "../../../shared/lib/format";
import { errorText, field, hint, label, secondaryButton } from "./formStyles";

type Props = {
  orders: OrderListItem[];
  loading: boolean;
  error: string;
  more: boolean;
  retry: () => void;
  value: string;
  onChange: (orderId: string) => void;
};

// A restart needs a confirmed order with the revised basket. The buyer picks it from the placed
// orders instead of pasting an id.
export function RestartOrderSelect({
  orders,
  loading,
  error,
  more,
  retry,
  value,
  onChange,
}: Props) {
  if (loading)
    return (
      <p role="status" className={hint}>
        Loading your placed orders…
      </p>
    );
  if (error)
    return (
      <div className="flex flex-wrap items-center gap-space-sm">
        <p role="alert" className={`${errorText} m-0`}>
          {error}
        </p>
        <button type="button" className={secondaryButton} onClick={retry}>
          Try again
        </button>
      </div>
    );
  if (orders.length === 0)
    return (
      <div className="flex flex-col items-start gap-space-xs">
        <p className="m-0 font-body text-body-md text-on-surface">
          No placed orders yet.
        </p>
        <p className={hint}>
          Place the revised order first, then restart the standing order from
          it.
        </p>
        <Link to="/purchases" className={secondaryButton}>
          Open past orders
        </Link>
      </div>
    );
  return (
    <div className="flex flex-col gap-1">
      <label className="flex flex-col gap-1">
        <span className={label}>Revised order to restart from</span>
        <select
          className={field}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Choose an order…</option>
          {orders.map((o) => (
            <option key={o.order_id} value={o.order_id ?? ""}>
              {[
                o.title ?? "Order",
                dateTime(o.updated_at),
                currency(o.gross_total, o.currency ?? "EUR"),
              ].join(" · ")}
            </option>
          ))}
        </select>
      </label>
      {!value && (
        <p className={hint}>
          Choose the confirmed revised order to restart from.
        </p>
      )}
      {more && <p className={hint}>Showing your 50 most recent orders.</p>}
    </div>
  );
}
