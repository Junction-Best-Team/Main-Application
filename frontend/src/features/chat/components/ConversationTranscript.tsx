import type { Conversation } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { dateTime } from "../../../shared/lib/format";
import { ChatActivity } from "./ChatActivity";
import { MealPlanCard } from "./MealPlanCard";
import { RecipeIllustration } from "./RecipeIllustration";
import { SkuCards } from "./SkuCards";
import { MessageMarkdown } from "./MessageMarkdown";
import { AttachmentCards } from "./AttachmentCards";
import { SystemMessage } from "./SystemMessage";
export function ConversationTranscript({
  conversation,
  busy,
  onReviewBasket,
}: {
  conversation: Conversation | null;
  busy: boolean;
  /** Opens the existing Overview / purchase handoff for this proposal. */
  onReviewBasket?: (proposalId: string) => void;
}) {
  return (
    <div
      role="log"
      aria-label="Conversation messages"
      aria-live="polite"
      aria-relevant="additions"
      className="flex flex-col gap-space-lg"
    >
      {conversation?.messages.map((message) =>
        message.role === "system" ? (
          <SystemMessage key={message.id} message={message} />
        ) : message.role === "user" ? (
          <article
            key={message.id}
            className="ml-auto flex max-w-2xl flex-row-reverse items-start gap-space-sm"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary dark:bg-primary-container shadow-sm">
              <Icon name="person" className="text-[18px]" />
            </div>
            <div className="flex min-w-0 flex-col items-end gap-space-xs">
              <AttachmentCards files={message.attachments ?? []} />
              {message.text && (
                <div className="max-w-full rounded-xl rounded-tr-none bg-primary dark:bg-primary-container px-space-md py-space-sm text-body-md text-on-primary shadow-sm">
                  <MessageMarkdown text={message.text} />
                </div>
              )}
              <MessageByline who="You" at={message.created_at} />
            </div>
          </article>
        ) : (
          <article
            key={message.id}
            className="flex max-w-3xl items-start gap-space-sm"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-wholesale-teal text-on-primary dark:bg-primary-container shadow-sm">
              <Icon name="smart_toy" className="text-[18px]" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
              <div className="rounded-xl rounded-tl-none bg-surface-container-low p-space-md shadow-sm">
                <div className="text-body-md text-on-surface">
                  <MessageMarkdown text={message.text} />
                </div>
                {message.image && (
                  <RecipeIllustration
                    key={message.image.url}
                    image={message.image}
                  />
                )}
                {message.meal_plan && (
                  <MealPlanCard
                    plan={message.meal_plan}
                    compact={conversation.purchases.some(
                      (p) => p.proposal_id === message.proposal_id,
                    )}
                  />
                )}
                {message.proposal_id && (
                  <>
                    <SkuCards
                      proposal={conversation.purchases.find(
                        (p) => p.proposal_id === message.proposal_id,
                      )}
                    />
                    {onReviewBasket &&
                      conversation.purchases.some(
                        (p) =>
                          p.proposal_id === message.proposal_id &&
                          p.order_status !== "accepted_mock",
                      ) && (
                        <div className="mt-space-md flex flex-col items-start gap-space-xs">
                          <button
                            type="button"
                            onClick={() => onReviewBasket(message.proposal_id!)}
                            className="rounded-lg bg-primary-container px-space-md py-space-sm font-label text-label-md font-bold text-on-primary transition-colors hover:bg-deep-ocean-navy focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container"
                          >
                            Review basket to confirm
                          </button>
                          <p className="text-label-sm text-secondary">
                            Sending chat never places an order.
                          </p>
                        </div>
                      )}
                  </>
                )}
              </div>
              <MessageByline who="Aimo" at={message.created_at} />
            </div>
          </article>
        ),
      )}
      <ChatActivity activity={conversation?.activity} busy={busy} />
    </div>
  );
}
function MessageByline({ who, at }: { who: string; at: string }) {
  return (
    <span className="mt-1 font-label text-label-sm text-secondary">
      {who} • <time dateTime={at}>{dateTime(at)}</time>
    </span>
  );
}
