import type { FormEvent } from "react";
type Props = {
  conversationId?: string;
  text: string;
  onTextChange: (text: string) => void;
  error: string;
  busy: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
};
export function ChatComposer({
  conversationId,
  text,
  onTextChange,
  error,
  busy,
  onSubmit,
}: Props) {
  return (
    <form
      className="chat-composer rounded-xl border border-border-subtle bg-surface-pure p-4 md:p-5 [&_label]:mb-3 [&_label]:block [&_label]:font-label [&_label]:text-label-md [&_label]:font-semibold [&_textarea]:block [&_textarea]:max-h-80 [&_textarea]:min-h-28 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-lg [&_textarea]:border-0 [&_textarea]:bg-surface-container-low [&_textarea]:p-3 [&_textarea]:text-body-md [&_textarea]:leading-relaxed"
      onSubmit={onSubmit}
    >
      <label htmlFor="purchase-message">
        {conversationId
          ? "Continue the conversation"
          : "Your meal or purchasing request"}
      </label>
      <textarea
        id="purchase-message"
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
        rows={3}
        maxLength={4000}
        placeholder="A meal, the number of portions, dietary needs…"
        disabled={Boolean(busy)}
        required
      />
      <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-center [&_p]:m-0 [&_p]:flex-1 [&_button]:shrink-0">
        <p className="text-body-sm text-secondary">
          Messages never authorize a purchase. You confirm the exact basket
          separately.
        </p>
        <button
          className="primary rounded border border-wholesale-teal bg-wholesale-teal px-5 py-3 font-label text-label-lg font-semibold text-on-primary hover:enabled:bg-deep-ocean-navy"
          disabled={Boolean(busy) || !text.trim()}
        >
          {busy ? "Working…" : error && text ? "Retry request" : "Send request"}
        </button>
      </div>
    </form>
  );
}
