import type { FormEvent } from "react";
import { Icon, InertButton } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
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
        disabled={Boolean(busy)}
        className="h-11 min-w-0 flex-1 rounded-lg bg-transparent p-space-sm font-body text-body-md text-on-surface placeholder:text-outline focus-visible:outline-2 focus-visible:outline-primary-container"
      />
      <div className="flex shrink-0 items-center gap-space-xs">
        <div className="flex items-center text-on-surface-variant md:gap-space-xs">
          <InertButton
            label="Attach file"
            className="flex h-11 w-7 items-center justify-center md:w-8"
          >
            <Icon name="attach_file" className="text-[20px] md:text-[24px]" />
          </InertButton>
          <InertButton
            label="Voice input"
            className="flex h-11 w-7 items-center justify-center md:w-8"
          >
            <Icon name="mic" className="text-[20px] md:text-[24px]" />
          </InertButton>
          <InertButton
            label="Scan barcode"
            className="flex h-11 w-7 items-center justify-center md:w-8"
          >
            <Icon
              name="barcode_scanner"
              className="text-[20px] md:text-[24px]"
            />
          </InertButton>
        </div>
        <button
          type="submit"
          aria-label={sendLabel}
          title={sendLabel}
          disabled={Boolean(busy) || !text.trim()}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary-container text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Icon name="arrow_forward" className="text-[22px]" />
        </button>
      </div>
    </form>
  );
}
