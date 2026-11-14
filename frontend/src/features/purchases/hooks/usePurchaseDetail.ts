import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { Proposal } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import {
  getPurchase,
  getApproval,
  confirmPurchase,
  rejectPurchase,
} from "../api/purchasesApi";
import { getPurchaseStatus } from "../model/purchaseStatus";
export function usePurchaseDetail({
  proposalId,
  approvalId,
}: {
  proposalId?: string;
  approvalId?: string;
}) {
  const { session, setSession } = useAuth();
  const currentDetail = `${proposalId ?? ""}/${approvalId ?? ""}`;
  const activeDetail = useRef(currentDetail);
  activeDetail.current = currentDetail;
  const [p, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    try {
      const result = proposalId
        ? await getPurchase(proposalId)
        : await getApproval(approvalId!);
      if (activeDetail.current !== `${proposalId ?? ""}/${approvalId ?? ""}`)
        return;
      setProposal(result);
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    }
  }, [approvalId, proposalId, setSession]);
  useEffect(() => {
    setProposal(null);
    setMessage("");
    void load();
  }, [load]);
  const terminal = p
    ? [
        "accepted_mock",
        "expired",
        "rejected",
        "superseded",
        "policy_changed",
      ].includes(getPurchaseStatus(p))
    : false;
  useRefresh(load, !terminal);
  async function reject() {
    if (!p || !session || !p.approval_id) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setProposal(
        await rejectPurchase(p.approval_id, p.revision, session.csrf_token),
      );
      setMessage("Rejection recorded. This purchase cannot be committed.");
    } catch (e) {
      const msg = (e as Error).message;
      await load();
      setError(msg);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!p || !session) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await confirmPurchase(p, session);
      await load();
      if (result.status === "revised") {
        setMessage(
          "Terms changed during verification. Review the new revision and confirm again.",
        );
      } else {
        setMessage("Confirmation saved. Your demo receipt is below.");
      }
    } catch (e) {
      const msg = (e as Error).message;
      await load();
      setError(msg);
    } finally {
      setBusy(false);
    }
  }
  const canConfirm =
    p &&
    p.revision === p.current_revision &&
    !terminal &&
    !["denied", "needs_resolution"].includes(p.policy_outcome) &&
    (p.policy_outcome === "ready_to_commit" ||
      p.can_decide ||
      p.approval_status === "approved");
  return {
    p,
    error,
    busy,
    message,
    load,
    confirm,
    reject,
    canConfirm: Boolean(canConfirm),
  };
}
