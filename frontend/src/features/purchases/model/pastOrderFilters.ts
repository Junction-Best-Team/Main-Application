import type { Proposal } from "../../../shared/api/types";
import { placedAt } from "./acceptedOrders";

export type PastOrderPeriod = "7d" | "30d" | "90d" | "all";
export type PastOrderSort = "newest" | "oldest" | "total_desc" | "total_asc";
export type PastOrderStatus = "all" | "accepted_mock";

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
  { value: "accepted_mock", label: "Status: Accepted" },
];

const DAY_MS = 24 * 60 * 60 * 1000;

function periodCutoff(period: PastOrderPeriod, now: number): number | null {
  if (period === "all") return null;
  const days = period === "7d" ? 7 : period === "30d" ? 30 : 90;
  return now - days * DAY_MS;
}

function matchesSearch(order: Proposal, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    order.order_id,
    order.proposal_id,
    order.request.request_id,
    order.request.destination,
    order.request.delivery_date,
    ...order.snapshot.lines.map((line) => line.name),
    ...order.snapshot.lines.map((line) => line.product_id),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

function withinPeriod(
  order: Proposal,
  period: PastOrderPeriod,
  now: number,
): boolean {
  const cutoff = periodCutoff(period, now);
  if (cutoff === null) return true;
  const placed = Date.parse(placedAt(order));
  if (Number.isNaN(placed)) return false;
  return placed >= cutoff;
}

function matchesStatus(order: Proposal, status: PastOrderStatus): boolean {
  if (status === "all") return true;
  return order.order_status === status;
}

function compareOrders(a: Proposal, b: Proposal, sort: PastOrderSort): number {
  if (sort === "total_desc" || sort === "total_asc") {
    const left = Number(a.snapshot.gross_total);
    const right = Number(b.snapshot.gross_total);
    const safeLeft = Number.isFinite(left) ? left : 0;
    const safeRight = Number.isFinite(right) ? right : 0;
    return sort === "total_desc" ? safeRight - safeLeft : safeLeft - safeRight;
  }
  const left = Date.parse(placedAt(a));
  const right = Date.parse(placedAt(b));
  const safeLeft = Number.isNaN(left) ? 0 : left;
  const safeRight = Number.isNaN(right) ? 0 : right;
  return sort === "oldest" ? safeLeft - safeRight : safeRight - safeLeft;
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

export function filterAndSortPastOrders(
  orders: Proposal[],
  filters: PastOrderFilters,
  now = Date.now(),
): Proposal[] {
  return orders
    .filter(
      (order) =>
        matchesSearch(order, filters.query) &&
        withinPeriod(order, filters.period, now) &&
        matchesStatus(order, filters.status),
    )
    .sort((a, b) => compareOrders(a, b, filters.sort));
}
