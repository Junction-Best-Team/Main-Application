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
