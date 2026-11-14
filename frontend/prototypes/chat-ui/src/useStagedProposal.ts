import { useEffect, useState } from "react";
import { store } from "./store";
import type { Conversation, Proposal } from "./types";

// The proposal staged in a conversation: its latest purchase, loaded in full.
// null while there is none (or while it loads).
export function useStagedProposal(conversation: Conversation | null) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState("");
  const proposalId = conversation?.purchases.at(-1)?.proposal_id;
  useEffect(() => {
    setProposal(null);
    setError("");
    if (!proposalId) return;
    let live = true;
    store
      .getProposal(proposalId)
      .then((p) => live && setProposal(p))
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [proposalId]);
  return { proposal, setProposal, error };
}
