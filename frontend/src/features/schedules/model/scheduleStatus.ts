import type {
  Recurrence,
  Schedule,
  ScheduleRun,
} from "../../../shared/api/types";

// The server gives the authorization status and the latest run; the card chip is derived here.
export type ChipTone = "positive" | "attention" | "neutral" | "negative";
export type ScheduleChip = { label: string; tone: ChipTone };

export function scheduleChip(
  schedule: Pick<Schedule, "status" | "next_run_date">,
): ScheduleChip {
  switch (schedule.status) {
    case "active":
      return { label: "Scheduled", tone: "positive" };
    case "paused":
      return { label: "Paused", tone: "neutral" };
    case "stopped":
      return { label: "Stopped, needs attention", tone: "attention" };
    case "cancelled":
      return { label: "Cancelled", tone: "neutral" };
    case "expired":
      return { label: "Expired", tone: "neutral" };
    case "superseded":
      return { label: "Replaced", tone: "neutral" };
    default:
      return { label: String(schedule.status), tone: "neutral" };
  }
}

// A stopped schedule that has been restarted has a successor; show the successor instead.
export const isSuperseded = (s: Pick<Schedule, "status" | "replaced_by">) =>
  s.status === "superseded" || (s.status === "stopped" && !!s.replaced_by);

// One plain sentence per stop reason (the server sends only the code).
export const STOP_REASON_TEXT: Record<string, string> = {
  PRODUCT_UNAVAILABLE: "A product was not available for the delivery date.",
  PRODUCT_WITHDRAWN: "A product has been withdrawn from the catalog.",
  PRICE_OUTSIDE_RANGE:
    "A price moved outside the range you accepted and no accepted substitute was available.",
  CEILING_EXCEEDED: "The total went above the price ceiling you agreed.",
  RUN_MISSED: "The run did not happen on its date.",
  POLICY_NOT_READY:
    "Your purchasing policy no longer allows this order as it stands.",
  RUN_TERMS_CHANGED: "The terms changed since you agreed to them.",
  AUTHORIZATION_WITHDRAWN: "The standing order authorization was withdrawn.",
  SCHEDULER_NOT_CONFIGURED: "Standing orders are not available right now.",
  UPSTREAM_UNAVAILABLE: "The supplier could not be reached.",
  UPSTREAM_RATE_LIMITED:
    "The supplier kept refusing requests as too many, even after several automatic retries.",
  // Codes raised by the order commit path; they arrive as free text.
  COMMIT_BLOCKED: "Your purchasing policy blocked the order.",
  APPROVAL_REQUIRED:
    "The order needs an approval that a standing order cannot give.",
  SCHEDULE_NOT_AUTHORIZED:
    "The standing order was not authorized for this run.",
  AUTHORITY_REVOKED: "Your authority for this order was withdrawn.",
  ALREADY_COMMITTED: "An order for this date already exists.",
  STALE_REVISION: "The proposed order changed before it could be placed.",
  CONSTRAINT_LOOSENED:
    "The basket would loosen a requirement you agreed, such as your diet or budget.",
  RUN_FAILED: "The run kept failing for a reason the system could not name.",
};

// Why a run was skipped (a skipped run is not a disruption).
export const SKIPPED_REASON_TEXT: Record<string, string> = {
  PAUSED: "Paused",
  AUTHORIZATION_CANCELLED: "The standing order was cancelled",
  AUTHORIZATION_SUPERSEDED: "The standing order was replaced",
  AUTHORIZATION_EXPIRED: "The standing order had expired",
  AUTHORIZATION_STOPPED: "The standing order was stopped",
};
export const skippedReasonText = (code?: string | null) =>
  SKIPPED_REASON_TEXT[code ?? "PAUSED"] ?? `Skipped (${code}).`;
export const stopReasonText = (code?: string | null) =>
  code ? (STOP_REASON_TEXT[code] ?? `Stopped (${code}).`) : "";

// These reasons need a new order from the customer to restart; the others may be retried by a
// restart of the same terms. The server decides what a restart accepts; this only picks wording.
export const needsNewOrderToRestart = (code?: string | null) =>
  code === "PRODUCT_UNAVAILABLE" ||
  code === "PRODUCT_WITHDRAWN" ||
  code === "PRICE_OUTSIDE_RANGE" ||
  code === "CEILING_EXCEEDED" ||
  code === "POLICY_NOT_READY" ||
  code === "RUN_TERMS_CHANGED";

export const RUN_STATUS_LABEL: Record<ScheduleRun["status"], string> = {
  due: "Due",
  prepared: "Prepared",
  committed: "Order placed",
  disrupted: "Needs your attention",
  skipped: "Skipped (paused)",
};

export const RUN_LINE_LABEL: Record<string, string> = {
  available_same_price: "Available at the agreed price",
  price_within_range: "Price changed within your range",
  substituted: "Substitute used",
  price_outside_range: "Price outside your range",
  unavailable: "Not available",
  withdrawn: "Withdrawn",
  blocked_by_policy: "Blocked by policy",
};

const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
export const weekdayName = (day: number) => WEEKDAYS[day] ?? "";

export function cadenceLabel(r: Recurrence): string {
  if (r.kind === "days") {
    return !r.interval || r.interval === 1
      ? "Every day"
      : `Every ${r.interval} days`;
  }
  const days = (r.weekdays ?? []).map(weekdayName).join(" and ");
  const every = r.every_weeks ?? 1;
  const base = days || "week";
  return every === 1
    ? `Every week on ${base}`
    : `Every ${every} weeks on ${base}`;
}

// Date-only values ("2026-11-14") are Helsinki calendar dates: never shift them by a time zone.
export const formatDate = (isoDate?: string | null) =>
  isoDate
    ? new Intl.DateTimeFormat("en-FI", {
        dateStyle: "medium",
        timeZone: "UTC",
      }).format(new Date(`${isoDate}T00:00:00Z`))
    : "";

// The server sends two-decimal strings ("7.50", "0.00").
export const percentLabel = (value?: string | null) =>
  `${Number(value ?? 0).toFixed(Number(value ?? 0) % 1 === 0 ? 0 : 2)} %`;
