import type { Ref } from "react";
import { Link } from "react-router-dom";
import type { Conversation } from "../../../shared/api/types";
import { dateTime } from "../../../shared/lib/format";
import { MealPlanCard } from "./MealPlanCard";
type Props = {
  conversation: Conversation | null;
  busy: boolean;
  transcript: Ref<HTMLDivElement>;
};
export function ConversationTranscript({
  conversation,
  busy,
  transcript,
}: Props) {
  return (
    <div
      className="transcript flex min-w-0 flex-col gap-6"
      aria-label="Conversation messages"
      aria-live="polite"
      aria-relevant="additions"
    >
      {conversation?.messages.map((message) => (
        <article
          className={`chat-message ${message.role} max-w-[94%] rounded-xl border p-4 md:max-w-[88%] md:p-5 ${message.role === "user" ? "ml-auto rounded-tr-none border-primary bg-primary text-on-primary" : "rounded-tl-none border-border-subtle bg-surface-pure text-on-surface"}`}
          key={message.id}
        >
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 font-label text-label-sm [&_time]:opacity-80">
            <strong>{message.role === "user" ? "You" : "Aimo"}</strong>
            <time dateTime={message.created_at}>
              {dateTime(message.created_at)}
            </time>
          </div>
          <p className="mb-0 whitespace-pre-wrap wrap-anywhere text-body-md">
            {message.text}
          </p>
          {message.meal_plan && <MealPlanCard plan={message.meal_plan} />}
          {message.proposal_id && (
            <Link
              className="mt-4 inline-flex rounded border border-wholesale-teal bg-surface-pure px-4 py-3 font-label text-label-md font-bold text-wholesale-teal hover:bg-secondary-container hover:no-underline"
              to={`/purchases/${message.proposal_id}`}
            >
              Review basket and purchasing checks
            </Link>
          )}
        </article>
      ))}
      {busy && (
        <p
          className="rounded-lg bg-secondary-container p-4 text-body-sm text-primary"
          role="status"
        >
          Aimo is checking your request… You can return to this conversation.
        </p>
      )}
      <div ref={transcript} />
    </div>
  );
}
