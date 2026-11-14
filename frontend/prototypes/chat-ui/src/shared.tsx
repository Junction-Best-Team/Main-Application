import type { ConversationPurchase, Proposal } from "./types";
import { proposalStatus } from "./store";

export { formatMoney as currency, formatDateTime as dateTime } from "./format";

export const title = (status: string) =>
  status.replaceAll("_", " ").replace(/^./, (s) => s.toUpperCase());

export function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{title(value)}</span>;
}

export function ErrorMessage({ message }: { message: string }) {
  return message ? (
    <div className="error" role="alert">
      {message}
    </div>
  ) : null;
}

export function statusOf(p: Proposal) {
  return proposalStatus(p);
}

export function purchaseStatus(purchase: ConversationPurchase) {
  if (purchase.approval_status === "superseded") return "superseded";
  if (purchase.order_status === "accepted_mock") return "accepted_mock";
  if (purchase.approval_status === "rejected") return "rejected";
  if (new Date(purchase.expires_at) <= new Date()) return "expired";
  return purchase.approval_status === "not_required" ? purchase.policy_outcome : purchase.approval_status;
}

export function canConfirm(p: Proposal) {
  return (
    p.revision === p.current_revision &&
    !["accepted_mock", "expired", "rejected", "superseded", "policy_changed"].includes(statusOf(p)) &&
    !["denied", "needs_resolution"].includes(p.policy_outcome) &&
    (p.policy_outcome === "ready_to_commit" || p.can_decide || p.approval_status === "approved")
  );
}
