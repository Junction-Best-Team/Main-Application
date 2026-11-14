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
      className="m-space-md mt-0 shrink-0 rounded-xl bg-surface-container-low p-space-sm shadow-sm"
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
        className="h-16 w-full resize-none font-body rounded-lg bg-transparent p-space-sm text-body-md text-on-surface placeholder:text-outline focus-visible:outline-2 focus-visible:outline-primary-container md:h-auto"
      />
      <div className="flex flex-wrap items-center justify-between gap-space-sm">
        <div className="flex items-center gap-space-xs text-on-surface-variant md:gap-space-sm">
          <InertButton label="Attach file" className="flex">
            <Icon name="attach_file" className="text-[20px] md:text-[24px]" />
          </InertButton>
          <InertButton label="Voice input" className="flex">
            <Icon name="mic" className="text-[20px] md:text-[24px]" />
          </InertButton>
          <InertButton label="Scan barcode" className="flex">
            <Icon
              name="barcode_scanner"
              className="text-[20px] md:text-[24px]"
            />
          </InertButton>
          <span className="hidden font-label text-label-sm text-secondary md:inline">
            {MOCK.request.composerHint}
          </span>
        </div>
        <button
          disabled={Boolean(busy) || !text.trim()}
          className="flex items-center gap-space-xs rounded-lg bg-primary-container px-space-sm py-space-sm font-label text-label-md text-on-primary disabled:cursor-not-allowed disabled:opacity-50 md:px-space-md md:text-label-lg"
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
