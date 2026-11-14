import { useEffect } from "react";
import type { Conversation } from "../../../shared/api/types";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { OverviewPanel } from "./OverviewPanel";
export function StagedOverview({
  conversation,
  selectedId,
}: {
  conversation: Conversation | null;
  selectedId?: string;
}) {
  const lastPlan = conversation?.messages
    .slice()
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" &&
        (message.meal_plan || message.proposal_id),
    );
  const draft =
    !selectedId && lastPlan?.meal_plan && !lastPlan.proposal_id
      ? lastPlan.meal_plan
      : undefined;
  const latest =
    conversation?.purchases.find((p) => p.proposal_id === selectedId) ??
    (draft ? undefined : conversation?.purchases.at(-1));
  const flow = usePurchaseDetail({ proposalId: latest?.proposal_id });
  const { load } = flow;
  useEffect(() => {
    void load();
  }, [load, latest?.revision, latest?.order_id, latest?.approval_status]);
  return (
    <OverviewPanel key={conversation?.id ?? "new"} flow={flow} draft={draft} />
  );
}
