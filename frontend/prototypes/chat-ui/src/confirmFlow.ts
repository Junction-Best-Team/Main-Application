import { useState } from "react";
import { store } from "./store";
import type { Proposal } from "./types";

// Confirm/reject logic for the sticky decision panel. The trust boundary: an
// authenticated, revision-bound action, never something chat text can
// trigger on its own.
export function useConfirmFlow(onUpdate: (p: Proposal) => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function confirm(proposal: Proposal) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await store.confirm(proposal.proposal_id, proposal.revision);
      onUpdate(result.proposal);
      setMessage(
        result.status === "revised"
          ? "Terms changed during verification. Review the new revision and confirm again."
          : "Confirmation saved. Your demo receipt is below.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reject(proposal: Proposal) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await store.reject(proposal.proposal_id);
      onUpdate(updated);
      setMessage("Rejection recorded. This purchase cannot be committed.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return { busy, message, error, confirm, reject };
}
