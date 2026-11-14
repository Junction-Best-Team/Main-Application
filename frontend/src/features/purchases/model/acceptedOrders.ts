import type { Proposal } from "../../../shared/api/types";
export const isAccepted = (p: Proposal) =>
  Boolean(p.order_id) && p.order_status === "accepted_mock";
export function placedAt(p: Proposal): string {
  const accepted = p.history?.find((e) => e.event === "purchase_confirmed");
  return typeof accepted?.created_at === "string"
    ? accepted.created_at
    : p.snapshot.observed_at;
}
