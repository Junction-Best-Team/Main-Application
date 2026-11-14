import type { ConversationPurchase, Proposal } from "./types";
import { proposalStatus } from "./store";

export { formatMoney as currency, formatDateTime as dateTime } from "./format";

export const title = (status: string) => status.replaceAll("_", " ").replace(/^./, (s) => s.toUpperCase());

// Status tag colours by status; anything else uses the neutral tag.
const BADGE_TONE: Record<string, string> = {
  pending: "bg-[#fff0c7] text-[#755000]",
  approval_required: "bg-[#fff0c7] text-[#755000]",
  approved: "bg-[#dff2e9] text-[#1c6048]",
  accepted_mock: "bg-[#dff2e9] text-[#1c6048]",
  ready_to_commit: "bg-[#dff2e9] text-[#1c6048]",
  rejected: "bg-error-container text-on-error-container",
  denied: "bg-error-container text-on-error-container",
  expired: "bg-error-container text-on-error-container",
};

export function Badge({ value }: { value: string }) {
  const tone = BADGE_TONE[value] ?? "bg-surface-container-high text-on-surface-variant";
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-[11px] py-[7px] text-[0.8rem] leading-[1.3] font-bold ${tone}`}
    >
      {title(value)}
    </span>
  );
}

export function ErrorMessage({ message }: { message: string }) {
  return message ? (
    <div role="alert" className="rounded-lg bg-error-container p-space-md text-on-error-container">
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
