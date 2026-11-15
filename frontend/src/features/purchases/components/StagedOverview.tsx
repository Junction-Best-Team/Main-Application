import { useEffect } from "react";
import type { Proposal } from "../../../shared/api/types";
import type { Conversation } from "../../../shared/api/types";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { notIncludedItems } from "../model/cart";
import { useCardLog } from "../model/cardLog";
import { getPurchaseStatus } from "../model/purchaseStatus";
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
  const showsDraft =
    Boolean(draft) &&
    !selectedId &&
    !conversation?.purchases.some((p) => p.proposal_id === draft?.proposal_id);
  const chosen = showsDraft
    ? "draft"
    : latest
      ? "prepared"
      : recipeDraft
        ? "recipe-draft"
        : "empty";
  // Diagnosis (debug mode only): which card was chosen and why. Ids, counts and states, no text.
  useCardLog({
    kind: "card",
    chosen,
    why: showsDraft
      ? "a draft cart exists and no purchase belongs to it"
      : latest
        ? selectedId
          ? "a purchase was selected"
          : "the newest basket that is not cancelled"
        : recipeDraft
          ? "an assistant plan without a purchase"
          : "no cart and no purchase",
    conversation: conversation?.id ?? null,
    hasDraftCart: Boolean(draft),
    purchases: conversation?.purchases.length ?? 0,
    basket: latest
      ? {
          id: latest.proposal_id,
          status: getPurchaseStatus(latest),
          revision: latest.revision,
        }
      : null,
    cartEditable: conversation ? Boolean(conversation.cart_editable) : null,
    cartEditReason: conversation?.cart_edit_reason ?? null,
    busy: Boolean(conversation?.busy),
    notIncluded: notIncludedItems(draft ?? null).length,
  });
  if (showsDraft && draft) {
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
      cartEdit={
        conversation
          ? {
              editable: Boolean(conversation.cart_editable),
              reason: conversation.cart_edit_reason ?? null,
            }
          : undefined
      }
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
