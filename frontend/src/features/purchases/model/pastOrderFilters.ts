import type { OrderListItem } from "../../../shared/api/types";

export type PastOrderPeriod = "7d" | "30d" | "90d" | "all";
export type PastOrderSort = "newest" | "oldest" | "total_desc" | "total_asc";
export type PastOrderStatus = "all" | OrderListItem["status"];

export const PAST_ORDER_PERIODS: { value: PastOrderPeriod; label: string }[] = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "all", label: "All time" },
];

export const PAST_ORDER_SORTS: { value: PastOrderSort; label: string }[] = [
  { value: "newest", label: "Sort: Most recent" },
  { value: "oldest", label: "Sort: Oldest" },
  { value: "total_desc", label: "Sort: Highest total" },
  { value: "total_asc", label: "Sort: Lowest total" },
];

export const PAST_ORDER_STATUSES: {
  value: PastOrderStatus;
  label: string;
}[] = [
  { value: "all", label: "Status: All" },
  { value: "scheduled", label: "Status: Scheduled" },
  { value: "pending", label: "Status: Pending" },
  { value: "placed", label: "Status: Placed" },
  { value: "cancelled", label: "Status: Cancelled" },
];

const DAY_MS = 24 * 60 * 60 * 1000;

function periodCutoff(period: PastOrderPeriod, now: number): number | null {
  if (period === "all") return null;
  const days = period === "7d" ? 7 : period === "30d" ? 30 : 90;
  return now - days * DAY_MS;
}

// The moment an order row belongs to: when it was placed, the date a scheduled row runs, or the
// last update. A scheduled row is in the future, so a "last N days" period never hides it.
export function orderTime(order: OrderListItem): number {
  const value = order.placed_at ?? order.scheduled_for ?? order.updated_at;
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function withinPeriod(
  order: OrderListItem,
  period: PastOrderPeriod,
  now: number,
): boolean {
  const cutoff = periodCutoff(period, now);
  if (cutoff === null) return true;
  return orderTime(order) >= cutoff;
}

function total(order: OrderListItem): number {
  const value = Number(order.gross_total);
  return Number.isFinite(value) ? value : 0;
}

function compareOrders(
  a: OrderListItem,
  b: OrderListItem,
  sort: PastOrderSort,
): number {
  if (sort === "total_desc") return total(b) - total(a);
  if (sort === "total_asc") return total(a) - total(b);
  return sort === "oldest"
    ? orderTime(a) - orderTime(b)
    : orderTime(b) - orderTime(a);
}

export type PastOrderFilters = {
  query: string;
  period: PastOrderPeriod;
  sort: PastOrderSort;
  status: PastOrderStatus;
};

export const DEFAULT_PAST_ORDER_FILTERS: PastOrderFilters = {
  query: "",
  period: "90d",
  sort: "newest",
  status: "all",
};

/**
 * What the server filters. Search and status are asked of GET /api/orders (`q` matches the title,
 * schedule title, ids, destination, delivery date, line names and product ids; `status` is a
 * status). Keeping this in one place makes a change of the server contract a one-line change.
 */
export function orderApiFilters(filters: PastOrderFilters): {
  status?: Exclude<PastOrderStatus, "all">;
  q?: string;
} {
  const q = filters.query.trim();
  return {
    ...(filters.status === "all" ? {} : { status: filters.status }),
    ...(q ? { q } : {}),
  };
}

/**
 * Period and sort run over the loaded rows (the server answers newest first). A row the page is
 * deep-linked to is never hidden by the period.
 */
export function filterAndSortPastOrders(
  orders: OrderListItem[],
  filters: PastOrderFilters,
  now = Date.now(),
  pinnedProposalId?: string,
): OrderListItem[] {
  return orders
    .filter(
      (order) =>
        (pinnedProposalId && order.proposal_id === pinnedProposalId) ||
        ((filters.status === "all" || order.status === filters.status) &&
          withinPeriod(order, filters.period, now)),
    )
    .sort((a, b) => compareOrders(a, b, filters.sort));
}
