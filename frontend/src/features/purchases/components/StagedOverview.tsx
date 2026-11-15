import { useEffect } from "react";
import type { Proposal } from "../../../shared/api/types";
import type { Conversation } from "../../../shared/api/types";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { OverviewPanel } from "./OverviewPanel";
import { DraftCartPanel } from "./DraftCartPanel";
// A chat can hold several baskets (a changed cart prepares a new one and cancels the older). The card
// is the newest one that is not cancelled; if all are, the newest.
const currentBasket = (conversation: Conversation | null) => {
  const all = conversation?.purchases ?? [];
  return (
    [...all]
      .reverse()
      .find((p) => (p.approval_status as string) !== "cancelled") ?? all.at(-1)
  );
};

export function StagedOverview({
  conversation,
  selectedId,
  onPrepared,
}: {
  conversation: Conversation | null;
  selectedId?: string;
  /** A purchase was prepared from the cart: the chat shows it in the Overview. */
  onPrepared?: (proposal: Proposal) => void;
}) {
  const lastPlan = conversation?.messages
    .slice()
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" &&
        (message.meal_plan || message.proposal_id),
    );
  const recipeDraft =
    !selectedId && lastPlan?.meal_plan && !lastPlan.proposal_id
      ? lastPlan.meal_plan
      : undefined;
  const latest =
    conversation?.purchases.find((p) => p.proposal_id === selectedId) ??
    (recipeDraft ? undefined : currentBasket(conversation));
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
    return (
      <DraftCartPanel
        key={conversation?.id}
        cart={draft}
        conversationId={conversation?.id}
        working={conversation?.busy}
        onPrepared={onPrepared}
      />
    );
  }
  // The card is always there: with nothing to order it is empty and its button is greyed out.
  return latest || recipeDraft ? (
    <OverviewPanel
      key={conversation?.id ?? "new"}
      flow={flow}
      draft={recipeDraft}
      conversationId={conversation?.id}
      cart={draft ?? null}
      working={conversation?.busy}
      onPrepared={onPrepared}
    />
  ) : (
    <DraftCartPanel
      key={conversation?.id ?? "new"}
      cart={null}
      conversationId={conversation?.id}
    />
  );
}
