import type { FormEvent } from "react";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useVoiceMode } from "../hooks/useVoiceMode";
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
  const voice = useVoiceMode();
  const disabled = Boolean(busy) || voice.active;
  const hasDraft = Boolean(text.trim());
  const sendLabel = busy
    ? "Working…"
    : error && text
      ? "Retry request"
      : "Send Order Request";
  return (
    <form
      onSubmit={onSubmit}
      className="m-space-md mt-0 flex shrink-0 items-center gap-space-sm rounded-xl bg-surface-container-low p-space-sm shadow-sm"
    >
      <label htmlFor="purchase-message" className="sr-only">
        {conversationId
          ? "Continue the conversation"
          : "Your meal or purchasing request"}
      </label>
      <input
        id="purchase-message"
        type="text"
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
        maxLength={4000}
        placeholder={MOCK.request.composerPlaceholder}
        disabled={disabled}
        className="h-11 min-w-0 flex-1 rounded-lg bg-transparent p-space-sm font-body text-body-md text-on-surface placeholder:text-outline focus-visible:outline-2 focus-visible:outline-primary-container"
      />
      {/* One action at a time: send while there is a draft, otherwise voice mode. */}
      {hasDraft ? (
        <button
          type="submit"
          aria-label={sendLabel}
          title={sendLabel}
          disabled={disabled}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary-container text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Icon name="arrow_forward" className="text-[22px]" />
        </button>
      ) : (
        <button
          type="button"
          aria-label="Start voice mode"
          title="Start voice mode"
          onClick={() => voice.start(conversationId)}
          disabled={disabled}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-surface-pure text-on-surface transition-colors hover:bg-surface-container-high focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg
            aria-hidden="true"
            focusable="false"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
          >
            <path d="M4 10v4M8 5v14M12 8v8M16 3v18M20 9v6" />
          </svg>
        </button>
      )}
    </form>
  );
}
