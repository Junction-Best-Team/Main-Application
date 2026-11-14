import { useEffect } from "react";
import type { Conversation } from "../../../shared/api/types";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { OverviewPanel } from "./OverviewPanel";
import { DraftCartPanel } from "./DraftCartPanel";
export function StagedOverview({
  conversation,
  selectedId,
}: {
  conversation: Conversation | null;
  selectedId?: string;
}) {
  const latest =
    conversation?.purchases.find((p) => p.proposal_id === selectedId) ??
    conversation?.purchases.at(-1);
  const flow = usePurchaseDetail({ proposalId: latest?.proposal_id });
  const { load } = flow;
  useEffect(() => {
    void load();
  }, [load, latest?.revision, latest?.order_id, latest?.approval_status]);
  const draft = conversation?.draft_cart;
  if (
    draft &&
    !selectedId &&
    !conversation?.purchases.some((p) => p.proposal_id === draft.proposal_id)
  ) {
    return <DraftCartPanel key={conversation?.id} cart={draft} />;
  }
  return latest ? (
    <OverviewPanel key={conversation?.id ?? "new"} flow={flow} />
  ) : null;
}
