import type { Conversation } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { dateTime } from "../../../shared/lib/format";

type ChatMessage = Conversation["messages"][number];

// Written by the server (for example when a standing-order run is disrupted), never typed by the
// customer. It is a neutral banner with no edit or retry action; the text is shown as given.
export function SystemMessage({ message }: { message: ChatMessage }) {
  return (
    <article
      aria-label="System message"
      className="flex max-w-3xl items-start gap-space-sm"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary-container text-on-secondary-container shadow-sm">
        <Icon name="campaign" className="text-[18px]" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
        <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-space-md">
          <p className="m-0 mb-space-xs font-label text-label-sm font-bold uppercase tracking-wider text-secondary">
            Valio Aimo system
          </p>
          <p className="m-0 whitespace-pre-wrap wrap-anywhere text-body-md text-on-surface">
            {message.text}
          </p>
        </div>
        <span className="font-label text-label-sm text-secondary">
          <time dateTime={message.created_at}>
            {dateTime(message.created_at)}
          </time>
        </span>
      </div>
    </article>
  );
}
