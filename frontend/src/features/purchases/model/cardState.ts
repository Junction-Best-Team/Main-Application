import type { Proposal } from "../../../shared/api/types";
import { CART_COPY } from "./cartCopy";
import { getPurchaseStatus } from "./purchaseStatus";

type Line = Proposal["snapshot"]["lines"][number];

// A weight or pack size inside a product name: "5 kg", "500 g", "1 L", "30 pcs", "0,5 l".
const SIZE = /\s*\b\d+(?:[.,]\d+)?\s?(?:kg|g|l|ml|cl|dl|pcs|pc|st|kpl)\b/gi;

/** The name shown on the card: the product name without its weight (display only; the data is unchanged). */
export const shortName = (name: string) =>
  name
    .replace(SIZE, "")
    .replace(/\s{2,}/g, " ")
    .trim() || name;

/**
 * Names for the rows of one basket: the short name, except that two rows which would look the same
 * ("Spaghetti 500 g" and "Spaghetti 5 kg") keep their full names so the customer can tell them apart.
 */
export function displayNames(names: string[]): string[] {
  const short = names.map(shortName);
  return names.map((full, i) =>
    short.filter((s) => s === short[i]).length > 1 ? full : short[i],
  );
}

/** The lines of a proposal whose pack count the server could not work out (QUANTITY_UNRESOLVED). */
export const unresolvedLines = (p: Proposal): Line[] =>
  p.reasons
    .filter((r) => r.code === "QUANTITY_UNRESOLVED" && r.product_id)
    .map((r) => p.snapshot.lines.find((l) => l.product_id === r.product_id))
    .filter((l): l is Line => Boolean(l));

/** Why a purchase that cannot be confirmed says so: short code for the debug log, one sentence for the customer. */
export function blockerOf(p: Proposal): { code: string; text: string } {
  const status = getPurchaseStatus(p);
  if (p.order_id)
    return { code: "order placed", text: CART_COPY.alreadyPlaced };
  const unresolved = unresolvedLines(p);
  if (unresolved.length > 0) {
    const names = displayNames(p.snapshot.lines.map((l) => l.name));
    const first = names[p.snapshot.lines.indexOf(unresolved[0])];
    return {
      code: "no pack size",
      text:
        `${first}: no pack size` +
        (unresolved.length > 1 ? ` (+${unresolved.length - 1} more)` : ""),
    };
  }
  if (["denied", "needs_resolution"].includes(p.policy_outcome))
    return { code: "checks blocked", text: CART_COPY.blockedByChecks };
  if (status === "expired") return { code: "expired", text: CART_COPY.expired };
  if (status === "rejected")
    return { code: "rejected", text: CART_COPY.rejected };
  if (status === "superseded")
    return { code: "superseded", text: CART_COPY.superseded };
  if (status === "pending")
    return { code: "not authorised", text: CART_COPY.noAuthority };
  return { code: "closed", text: CART_COPY.closed };
}

/** Something blocks the order (not just "waiting for a decision"): shown as a badge on the Checks tab. */
export function blocking(p: Proposal): boolean {
  if (p.order_id) return false;
  const status = getPurchaseStatus(p);
  return (
    ["denied", "needs_resolution"].includes(p.policy_outcome) ||
    ["expired", "rejected", "superseded", "policy_changed"].includes(status)
  );
}

/** The badge text on the Checks tab: how many checks block, or "!" when it is blocked without a reason. */
export function checksBadge(p: Proposal): string | null {
  if (!blocking(p)) return null;
  const n = p.reasons.filter((r) =>
    ["denied", "unresolved"].includes(r.severity),
  ).length;
  return n > 0 ? String(n) : "!";
}

const DAY = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});
/** "Tue 17 Nov" from a YYYY-MM-DD delivery date. */
export function shortDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? date : DAY.format(parsed);
}

/** The delivery in one line; it reads differently once the order is placed or while it is blocked. */
export function deliveryLine(p: Proposal): string {
  const base = `${shortDate(p.request.delivery_date)} · ${p.request.destination}`;
  if (p.order_id) return `Order placed · ${base}`;
  return blocking(p) ? `Blocked · ${base}` : base;
}
