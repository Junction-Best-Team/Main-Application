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
  const [snapshot, setSnapshot] = useState<{ key: string; p: Proposal } | null>(
    null,
  );
  const p = snapshot?.key === currentDetail ? snapshot.p : null;
  const sequence = useRef(0);
  const actionInFlight = useRef(false);
  const setProposal = (value: Proposal) =>
    setSnapshot({ key: currentDetail, p: value });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    if ((!proposalId && !approvalId) || activeDetail.current !== currentDetail)
      return;
    const request = ++sequence.current;
    try {
      const result = proposalId
        ? await getPurchase(proposalId)
        : await getApproval(approvalId!);
      if (
        activeDetail.current !== currentDetail ||
        sequence.current !== request
      )
        return;
      setSnapshot({ key: currentDetail, p: result });
      setError("");
    } catch (e) {
      if (
        activeDetail.current !== currentDetail ||
        sequence.current !== request
      )
        return;
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    }
  }, [approvalId, proposalId, setSession, currentDetail]);
  useEffect(() => {
    setSnapshot(null);
    setError("");
    setBusy(false);
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
  useRefresh(load, Boolean(proposalId || approvalId) && !terminal);
  async function reject() {
    if (!p || !session || !p.approval_id || actionInFlight.current) return;
    actionInFlight.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await rejectPurchase(
        p.approval_id,
        p.revision,
        session.csrf_token,
      );
      if (activeDetail.current !== currentDetail) return;
      setProposal(result);
      setMessage("Rejection recorded. This purchase cannot be committed.");
    } catch (e) {
      const msg = (e as Error).message;
      await load();
      if (activeDetail.current === currentDetail) setError(msg);
    } finally {
      actionInFlight.current = false;
      if (activeDetail.current === currentDetail) setBusy(false);
    }
  }
  async function confirm() {
    if (!p || !session || actionInFlight.current) return;
    actionInFlight.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await confirmPurchase(p, session);
      await load();
      if (activeDetail.current !== currentDetail) return;
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
      if (activeDetail.current === currentDetail) setError(msg);
    } finally {
      actionInFlight.current = false;
      if (activeDetail.current === currentDetail) setBusy(false);
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
