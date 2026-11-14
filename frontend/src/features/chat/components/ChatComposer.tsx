import { useEffect, useRef, useState, type FormEvent } from "react";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useVoiceMode } from "../hooks/useVoiceMode";
import { AttachmentCards } from "./AttachmentCards";
import {
  ACCEPT_FILES,
  attachmentSize,
  readAttachments,
  type ChatAttachment,
} from "../model/attachments";
type Props = {
  conversationId?: string;
  text: string;
  onTextChange: (text: string) => void;
  error: string;
  busy: boolean;
  attachments: ChatAttachment[];
  onAttachmentsChange: (files: ChatAttachment[]) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
};
export function ChatComposer({
  conversationId,
  text,
  onTextChange,
  error,
  busy,
  attachments,
  onAttachmentsChange,
  onSubmit,
}: Props) {
  const voice = useVoiceMode();
  const picker = useRef<HTMLInputElement>(null);
  const readingRef = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [reading, setReading] = useState(false);
  const [fileError, setFileError] = useState("");
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const disabled = Boolean(busy) || voice.active;
  // One action at a time: send while there is a draft or attachment, otherwise voice.
  const hasDraft = Boolean(text.trim()) || attachments.length > 0;
  async function addFiles(files: File[]) {
    if (disabled || readingRef.current || !files.length) return;
    readingRef.current = true;
    setReading(true);
    setFileError("");
    try {
      const next = await readAttachments(files, attachments);
      if (mounted.current) onAttachmentsChange(next);
    } catch (error) {
      setFileError((error as Error).message);
    } finally {
      readingRef.current = false;
      setReading(false);
    }
  }
  const sendLabel = busy
    ? "Working…"
    : error && (text || attachments.length)
      ? "Retry request"
      : "Send Order Request";
  return (
    <form
      onSubmit={(event) => {
        if (reading || disabled) event.preventDefault();
        else void onSubmit(event);
      }}
      onDragEnter={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          dragDepth.current++;
          setDragging(true);
        }
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          event.dataTransfer.dropEffect = disabled ? "none" : "copy";
        }
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        dragDepth.current--;
        if (dragDepth.current <= 0) {
          dragDepth.current = 0;
          setDragging(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        void addFiles(Array.from(event.dataTransfer.files));
      }}
      onPaste={(event) => {
        if (event.clipboardData.files.length) {
          event.preventDefault();
          void addFiles(Array.from(event.clipboardData.files));
        }
      }}
      aria-label="Chat message"
      className={`m-space-md mt-0 flex shrink-0 flex-col gap-space-sm rounded-xl bg-surface-container-low p-space-sm shadow-sm ${dragging ? "outline-2 outline-primary-container" : ""}`}
    >
      <AttachmentCards
        files={attachments.map((file) => ({
          ...file,
          size: attachmentSize(file),
          url: `data:${file.media_type};base64,${file.data}`,
        }))}
        onRemove={(index) => {
          onAttachmentsChange(attachments.filter((_, i) => i !== index));
          setFileError("");
        }}
        disabled={disabled || reading}
      />
      {fileError && (
        <p role="alert" className="text-body-sm text-error">
          {fileError}
        </p>
      )}
      {(dragging || reading) && (
        <p className="px-space-sm text-label-sm text-secondary" role="status">
          {dragging ? "Drop files here" : "Reading files…"}
        </p>
      )}
      <div className="flex w-full min-w-0 items-center gap-space-sm">
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
          className="h-11 min-w-0 flex-1 rounded-lg bg-transparent p-space-sm font-body text-body-md text-on-surface placeholder:text-outline focus:outline-none focus-visible:outline-none"
        />
        <div className="flex shrink-0 items-center gap-space-xs">
          <div className="flex items-center text-on-surface-variant md:gap-space-xs">
            <input
              ref={picker}
              type="file"
              multiple
              accept={ACCEPT_FILES}
              className="sr-only"
              tabIndex={-1}
              aria-label="Choose attachments"
              disabled={disabled || reading}
              onChange={(event) => {
                void addFiles(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
            <button
              type="button"
              aria-label="Attach file"
              onClick={() => picker.current?.click()}
              disabled={disabled || reading}
              className="flex h-11 w-7 items-center justify-center md:w-8"
            >
              <Icon name="attach_file" className="text-[20px] md:text-[24px]" />
            </button>
          </div>
          {hasDraft ? (
            <button
              type="submit"
              aria-label={sendLabel}
              title={sendLabel}
              disabled={disabled || reading}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary-container text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Icon name="arrow_forward" className="text-[22px]" />
            </button>
          ) : (
            <button
              type="button"
              aria-label="Start voice mode"
              title="Start voice mode"
              onClick={() => voice.start(conversationId)}
              disabled={disabled || reading}
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
        </div>
      </div>
    </form>
  );
}
