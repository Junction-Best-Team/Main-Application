import type { Proposal } from "../../../shared/api/types";

export function getPurchaseStatus(p: Proposal) {
  if (p.approval_status === "superseded") return "superseded";
  if (p.order_status === "accepted_mock") return "accepted_mock";
  if (p.approval_status === "rejected") return "rejected";
  if (new Date(p.expires_at) <= new Date()) return "expired";
  return p.approval_status === "not_required"
    ? p.policy_outcome
    : p.approval_status;
}
