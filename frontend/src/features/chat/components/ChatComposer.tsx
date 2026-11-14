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
  return (
    <form
      onSubmit={onSubmit}
      className="m-space-md mt-0 rounded-xl bg-surface-container-low p-space-sm shadow-sm"
    >
      <label htmlFor="purchase-message" className="sr-only">
        {conversationId
          ? "Continue the conversation"
          : "Your meal or purchasing request"}
      </label>
      <textarea
        id="purchase-message"
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        rows={3}
        maxLength={4000}
        placeholder={MOCK.request.composerPlaceholder}
        disabled={Boolean(busy)}
        className="w-full resize-none font-body rounded-lg bg-transparent p-space-sm text-body-md text-on-surface placeholder:text-outline focus-visible:outline-2 focus-visible:outline-primary-container"
      />
      <div className="flex flex-wrap items-center justify-between gap-space-sm">
        <div className="flex items-center gap-space-sm text-on-surface-variant">
          <InertButton label="Attach file" className="flex">
            <Icon name="attach_file" />
          </InertButton>
          <InertButton label="Voice input" className="flex">
            <Icon name="mic" />
          </InertButton>
          <InertButton label="Scan barcode" className="flex">
            <Icon name="barcode_scanner" />
          </InertButton>
          <span className="hidden font-label text-label-sm text-secondary md:inline">
            {MOCK.request.composerHint}
          </span>
        </div>
        <button
          disabled={Boolean(busy) || !text.trim()}
          className="flex items-center gap-space-xs rounded-lg bg-primary-container px-space-md py-space-sm font-label text-label-lg text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy
            ? "Working…"
            : error && text
              ? "Retry request"
              : "Send Order Request"}
          <Icon name="arrow_upward" className="text-[18px]" />
        </button>
      </div>
    </form>
  );
}
