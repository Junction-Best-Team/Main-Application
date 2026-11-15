import type { OrderListItem } from "../../../shared/api/types";

// Where an order is on its journey (Placed or Scheduled, Paid, Delivered, Confirmed), shared by
// the status bar (OrderStatus) and the row's background pattern (OrderRowDecor).

export type Tone =
  "neutral" | "muted" | "teal" | "amber" | "lime" | "green" | "error";

export type Stage = {
  key: string;
  label: string;
  /** 1 Placed/Scheduled, 2 Paid, 3 Delivered, 4 Confirmed (fractions sit between stops);
   *  0 = before the first stop. */
  progress: number;
  tone: Tone;
  /** Draw the current stop as a ring: not reached yet. */
  hollow?: boolean;
  /** Something is happening right now (pending: breathing ring; on the way: glint). */
  live?: boolean;
  /** Bars drawn dashed: on hold or stopped. */
  dashed?: boolean;
  cancelled?: boolean;
};

export function stageOf(item: OrderListItem): Stage {
  if (item.status === "cancelled")
    return {
      key: "cancelled",
      label: "Cancelled",
      progress: 1,
      tone: "error",
      dashed: true,
      cancelled: true,
    };
  if (item.status === "pending")
    return {
      key: "pending",
      label: "Pending",
      progress: 1,
      tone: "amber",
      hollow: true,
      live: true,
    };
  if (item.status === "scheduled")
    return item.paused
      ? {
          key: "scheduled",
          label: "Scheduled",
          progress: 1,
          tone: "muted",
          hollow: true,
          dashed: true,
        }
      : {
          key: "scheduled",
          label: "Scheduled",
          progress: 1,
          tone: "neutral",
          hollow: true,
        };
  // Placed orders follow the (simulated) fulfilment.
  switch (item.fulfilment?.status) {
    case "preparing":
      return { key: "placed", label: "Paid", progress: 2, tone: "teal" };
    case "out_for_delivery":
      return {
        key: "placed",
        label: "Out for delivery",
        progress: 2.5,
        tone: "lime",
        live: true,
      };
    case "delivered":
      return { key: "placed", label: "Delivered", progress: 3, tone: "green" };
    default:
      return { key: "placed", label: "Placed", progress: 1, tone: "teal" };
  }
}
