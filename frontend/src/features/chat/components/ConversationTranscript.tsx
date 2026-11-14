import type { Ref } from "react";
import type { Conversation } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { dateTime } from "../../../shared/lib/format";
import { MealPlanCard } from "./MealPlanCard";
import { RecipeIllustration } from "./RecipeIllustration";
import { SkuCards } from "./SkuCards";
export function ConversationTranscript({
  conversation,
  busy,
  transcript,
}: {
  conversation: Conversation | null;
  busy: boolean;
  transcript: Ref<HTMLDivElement>;
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
        message.role === "user" ? (
          <article
            key={message.id}
            className="ml-auto flex max-w-2xl flex-row-reverse items-start gap-space-sm"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary shadow-sm">
              <Icon name="person" className="text-[18px]" />
            </div>
            <div className="flex min-w-0 flex-col items-end">
              <p className="whitespace-pre-wrap wrap-anywhere rounded-xl rounded-tr-none bg-primary px-space-md py-space-sm text-body-md text-on-primary shadow-sm">
                {message.text}
              </p>
              <MessageByline who="You" at={message.created_at} />
            </div>
          </article>
        ) : (
          <article
            key={message.id}
            className="flex max-w-3xl items-start gap-space-sm"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-wholesale-teal text-on-primary shadow-sm">
              <Icon name="smart_toy" className="text-[18px]" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
              <div className="rounded-xl rounded-tl-none bg-surface-container-low p-space-md shadow-sm">
                <p className="whitespace-pre-wrap wrap-anywhere text-body-md text-on-surface">
                  {message.text}
                </p>
                {message.image && (
                  <RecipeIllustration
                    key={message.image.url}
                    image={message.image}
                  />
                )}
                {message.meal_plan && <MealPlanCard plan={message.meal_plan} />}
                {message.proposal_id && (
                  <SkuCards
                    proposal={conversation.purchases.find(
                      (p) => p.proposal_id === message.proposal_id,
                    )}
                  />
                )}
              </div>
              <MessageByline who="Aimo" at={message.created_at} />
            </div>
          </article>
        ),
      )}
      {busy && (
        <p className="text-body-sm text-secondary" role="status">
          Aimo is checking your request… You can return to this conversation.
        </p>
      )}
      <div ref={transcript} />
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
