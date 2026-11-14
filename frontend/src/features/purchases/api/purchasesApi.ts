import { api } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";
import type {
  Inbox,
  Proposal,
  Commit,
  Session,
} from "../../../shared/api/types";
export const listPurchases = (offset = 0) =>
  api<Inbox>(`/api/purchases?offset=${offset}&limit=20`);
export const getPurchase = (id: string) =>
  api<Proposal>(`/api/purchases/${id}`);
export const getApproval = (id: string) =>
  api<Proposal>(`/api/approvals/${id}`);
export const rejectPurchase = (
  approvalId: string,
  revision: number,
  csrfToken: string,
) =>
  api<Proposal>(`/api/approvals/${approvalId}/decision`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({
      decision: "reject",
      revision,
    } satisfies components["schemas"]["DecisionRequest"]),
  });
export async function confirmPurchase(proposal: Proposal, session: Session) {
  const actorHash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(session.username),
  );
  const actorKey = Array.from(new Uint8Array(actorHash))
    .slice(0, 12)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return api<Commit>(`/api/purchases/${proposal.proposal_id}/confirm`, {
    method: "POST",
    headers: { "X-CSRF-Token": session.csrf_token },
    body: JSON.stringify({
      proposal_id: proposal.proposal_id,
      revision: proposal.revision,
      idempotency_key: `customer-confirm-${proposal.proposal_id}-${proposal.revision}-${actorKey}`,
    } satisfies components["schemas"]["CommitRequest"]),
  });
}
