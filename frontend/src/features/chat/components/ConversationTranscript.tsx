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
      className="transcript"
      aria-label="Conversation messages"
      aria-live="polite"
      aria-relevant="additions"
    >
      {conversation?.messages.map((message) => (
        <article className={`chat-message ${message.role}`} key={message.id}>
          <div className="message-byline">
            <strong>{message.role === "user" ? "You" : "Aimo"}</strong>
            <time dateTime={message.created_at}>
              {dateTime(message.created_at)}
            </time>
          </div>
          <p className="message-text">{message.text}</p>
          {message.meal_plan && <MealPlanCard plan={message.meal_plan} />}
          {message.proposal_id && (
            <Link
              className="basket-link"
              to={`/purchases/${message.proposal_id}`}
            >
              Review basket and purchasing checks
            </Link>
          )}
        </article>
      ))}
      {busy && (
        <p className="agent-working" role="status">
          Aimo is checking your request… You can return to this conversation.
        </p>
      )}
      <div ref={transcript} />
    </div>
  );
}
