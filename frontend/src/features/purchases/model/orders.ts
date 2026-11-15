import type { OrderListItem, Proposal } from "../../../shared/api/types";
import { placedAt } from "./acceptedOrders";

export type OrderStatus = OrderListItem["status"];
export type OrderFilter = "all" | OrderStatus;

export const ORDER_FILTERS: { value: OrderFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "scheduled", label: "Scheduled" },
  { value: "pending", label: "Pending" },
  { value: "placed", label: "Placed" },
  { value: "cancelled", label: "Cancelled" },
];

// One plain sentence for why a request was cancelled (the server sends only the code).
export function cancelReasonText(reason?: OrderListItem["cancel_reason"]) {
  switch (reason) {
    case "run_disrupted":
      return "Cancelled because a standing-order run was disrupted";
    case "customer_revised":
      return "Replaced by a revised request";
    case "customer_cancelled":
      return "Cancelled by you";
    default:
      return "Cancelled";
  }
}

// Scheduled rows have no proposal; pending, placed and cancelled rows can share one, so the
// status is part of the identity.
export const orderKey = (item: OrderListItem, index: number) =>
  `${item.status}:${item.proposal_id ?? item.schedule_id ?? "row"}:${item.scheduled_for ?? index}`;

// A deep link can point at a placed order older than the loaded pages; show it as a placed row.
export function placedItemFromProposal(p: Proposal): OrderListItem {
  return {
    status: "placed",
    title: p.request.request_id,
    proposal_id: p.proposal_id,
    order_id: p.order_id,
    paused: false,
    gross_total: p.snapshot.gross_total,
    currency: p.snapshot.currency,
    line_count: p.snapshot.lines.length,
    updated_at: placedAt(p),
  };
}

// The list has no delivery date for placed orders, but its simulated fulfilment follows fixed
// rules (aimo/clock.py): preparing from D-1 00:00, out for delivery from D 06:00, delivered
// from D 12:00 (Helsinki). So the delivery day D can be read off the stage's start or end.
const helsinkiDay = (iso: string) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Helsinki",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
  return parts; // YYYY-MM-DD
};
const nextDay = (day: string) => {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
};

/** The delivery date (YYYY-MM-DD) of a placed order, from its fulfilment; null if unknown. */
export function deliveryDay(
  fulfilment?: {
    status: string;
    since?: string | null;
    next_at?: string | null;
  } | null,
): string | null {
  if (!fulfilment) return null;
  const { status, since, next_at } = fulfilment;
  if (status === "accepted" && next_at) return nextDay(helsinkiDay(next_at));
  if ((status === "preparing" || status === "out_for_delivery") && next_at)
    return helsinkiDay(next_at);
  if (status === "delivered" && since) return helsinkiDay(since);
  return null;
}
