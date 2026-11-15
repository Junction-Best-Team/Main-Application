import type { Proposal } from "../../../shared/api/types";
import { shortName } from "./cardState";

// The purchasing checks, grouped by what the customer can do about them (c5's checkout-blockers report):
//   blocker   the customer cannot approve: choose another product or ask the assistant
//   exception the customer can approve: SUBSTITUTION / OVERBUY
//   warning   blocks nothing: the amount is an estimate
//   expired   the approval ran out: refresh
// The class comes from ONE function, `classOf`: the proposal's `reason_classes[code]` when the server sends
// it (additive field), else this table, else the check's severity.
export type CheckClass =
  "blocker" | "exception" | "warning" | "expired" | "info"; // a note that is none of these (e.g. WITHIN_AUTHORITY, severity "info"): shown plainly, no group
type Reason = Proposal["reasons"][number];

const BY_CODE: Record<string, CheckClass> = {
  UNVERIFIED_STOCK: "blocker",
  QUANTITY_UNRESOLVED: "blocker",
  TOTAL_UNRESOLVED: "blocker",
  CUTOFF_PASSED: "blocker",
  SUBSTITUTION_REQUIRES_APPROVAL: "exception",
  OVERBUY_REQUIRES_APPROVAL: "exception",
  VARIABLE_WEIGHT_UNRESOLVED: "warning",
};
const BY_SEVERITY: Record<Reason["severity"], CheckClass> = {
  denied: "blocker",
  unresolved: "blocker",
  exception: "exception",
  warning: "warning",
};
const CLASSES: CheckClass[] = [
  "blocker",
  "exception",
  "warning",
  "expired",
  "info",
];

/** Short human text per code (minimal on purpose); unknown codes show the server's own message. */
const SHORT: Record<string, string> = {
  UNVERIFIED_STOCK: "Stock not confirmed",
  QUANTITY_UNRESOLVED: "No pack size",
  TOTAL_UNRESOLVED: "Total unknown",
  CUTOFF_PASSED: "Order cutoff passed",
  SUBSTITUTION_REQUIRES_APPROVAL: "Substitute product",
  OVERBUY_REQUIRES_APPROVAL: "Pack larger than needed",
  VARIABLE_WEIGHT_UNRESOLVED: "Weight varies",
};

export const CHECK_GROUPS: {
  cls: Exclude<CheckClass, "expired">;
  heading: string;
  action: string;
}[] = [
  {
    cls: "blocker",
    heading: "Cannot order yet",
    action: "Choose another product or ask the assistant.",
  },
  {
    cls: "exception",
    heading: "Needs your approval",
    action: "Approve below.",
  },
  {
    cls: "warning",
    heading: "Good to know",
    action: "Nothing, the amount is an estimate.",
  },
];
export const EXPIRED_GROUP = {
  heading: "Expired",
  text: "This approval expired.",
  action: "Refresh",
};

export function classOf(p: Proposal, r: Reason): CheckClass {
  const sent = (p as { reason_classes?: Record<string, string> })
    .reason_classes?.[r.code];
  if (sent && (CLASSES as string[]).includes(sent)) return sent as CheckClass;
  // An unknown code with a severity outside the four (older or newer server) blocks nothing: a note.
  return BY_CODE[r.code] ?? BY_SEVERITY[r.severity] ?? "info";
}

export type CheckItem = { code: string; text: string; product?: string };
const toItem = (p: Proposal, r: Reason): CheckItem => {
  const line = r.product_id
    ? p.snapshot.lines.find((l) => l.product_id === r.product_id)
    : undefined;
  return {
    code: r.code,
    text: SHORT[r.code] ?? r.message,
    product: line ? shortName(line.name) : undefined,
  };
};

/** The checks of a proposal split by class, in the order they are shown. */
export function groupChecks(p: Proposal): Record<CheckClass, CheckItem[]> {
  const out: Record<CheckClass, CheckItem[]> = {
    blocker: [],
    exception: [],
    warning: [],
    expired: [],
    info: [],
  };
  for (const r of p.reasons) out[classOf(p, r)].push(toItem(p, r));
  return out;
}

/** Blocked by the policy outcome even if no reason was listed. */
export const outcomeBlocks = (p: Proposal) =>
  ["denied", "needs_resolution"].includes(p.policy_outcome);
