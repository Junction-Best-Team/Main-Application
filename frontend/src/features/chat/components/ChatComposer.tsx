import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useVoiceMode } from "../hooks/useVoiceMode";
import { AttachmentCards } from "./AttachmentCards";
import {
  attachmentSize,
  readAttachments,
  type ChatAttachment,
} from "../model/attachments";
const composerActionClassName =
  "flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-status-fresh-green text-deep-ocean-navy transition-colors hover:enabled:bg-tertiary-fixed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container disabled:cursor-not-allowed disabled:opacity-50";

type Props = {
  appearance?: "chat" | "home";
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
  appearance = "chat",
  conversationId,
  text,
  onTextChange,
  error,
  busy,
  attachments,
  onAttachmentsChange,
  onSubmit,
}: Props) {
  const home = appearance === "home";
  const voice = useVoiceMode();
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
  function handleComposerKeyDown(
    event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) {
    if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    if (!hasDraft || disabled || reading) return;
    event.currentTarget.form?.requestSubmit();
  }
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
      className={`${home ? "home-composer" : "m-space-md mt-0 flex shrink-0 flex-col gap-space-md rounded-xl bg-surface-container-low p-space-sm shadow-sm"} ${dragging ? "outline-2 outline-primary-container" : ""}`}
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
      <div
        className={
          home
            ? "flex w-full min-w-0 flex-col"
            : "flex w-full min-w-0 items-center gap-space-sm"
        }
      >
        <label htmlFor="purchase-message" className="sr-only">
          {conversationId
            ? "Continue the conversation"
            : "Your meal or purchasing request"}
        </label>
        {home ? (
          <textarea
            id="purchase-message"
            value={text}
            onChange={(event) => onTextChange(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            maxLength={4000}
            placeholder="Tell Aimo what you need…"
            className="focus:outline-none focus-visible:outline-none"
            disabled={disabled}
            rows={2}
          />
        ) : (
          <input
            id="purchase-message"
            type="text"
            value={text}
            onChange={(event) => onTextChange(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            maxLength={4000}
            placeholder={MOCK.request.composerPlaceholder}
            disabled={disabled}
            className="h-11 min-w-0 flex-1 rounded-lg bg-transparent p-space-sm font-body text-body-md text-on-surface placeholder:text-outline focus:outline-none focus-visible:outline-none"
          />
        )}
        <div
          className={
            home
              ? "home-composer-actions w-full"
              : "flex shrink-0 items-center gap-space-xs"
          }
        >
          {hasDraft ? (
            <button
              type="submit"
              aria-label={sendLabel}
              title={sendLabel}
              disabled={disabled || reading}
              className={composerActionClassName}
            >
              <svg
                aria-hidden="true"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 20V4m-7 7 7-7 7 7" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              aria-label="Start voice mode"
              title="Start voice mode"
              onClick={() => voice.start(conversationId)}
              disabled={disabled || reading}
              className={composerActionClassName}
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
