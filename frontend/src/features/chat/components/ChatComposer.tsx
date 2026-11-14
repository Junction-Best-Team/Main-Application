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
    <form className="chat-composer" onSubmit={onSubmit}>
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
      <div className="composer-footer">
        <p className="muted small">
          Messages never authorize a purchase. You confirm the exact basket
          separately.
        </p>
        <button className="primary" disabled={Boolean(busy) || !text.trim()}>
          {busy ? "Working…" : error && text ? "Retry request" : "Send request"}
        </button>
      </div>
    </form>
  );
}
