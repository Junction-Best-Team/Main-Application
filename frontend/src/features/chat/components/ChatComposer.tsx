import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { useVoiceMode } from "../hooks/useVoiceMode";
import type { QueuedMessage } from "../hooks/useChat";
import { AttachmentCards } from "./AttachmentCards";
import {
  attachmentSize,
  readAttachments,
  type ChatAttachment,
} from "../model/attachments";
const composerActionClassName =
  "flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary-container text-on-primary transition-colors hover:enabled:bg-deep-ocean-navy focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container disabled:cursor-not-allowed disabled:opacity-50";

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
  /** Messages typed while Aimo answers. Passing a queue lets Enter queue while busy. */
  queue?: QueuedMessage[];
  queuePaused?: boolean;
  onRemoveQueued?: (id: string) => void;
  onSendQueued?: (id: string) => void;
  /** Same cancel path as Escape while a turn is in flight. */
  onCancel?: () => void;
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
  queue,
  queuePaused,
  onRemoveQueued,
  onSendQueued,
  onCancel,
}: Props) {
  const home = appearance === "home";
  const voice = useVoiceMode();
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  // Keep the caret in the composer: on arrival, after sending and after queue
  // actions. Touch screens skip the mount focus so the keyboard does not pop up.
  const focusInput = () => inputRef.current?.focus({ preventScroll: true });
  useEffect(() => {
    if (window.matchMedia?.("(pointer: fine)").matches) focusInput();
  }, []);
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
  const canQueue = Boolean(queue && conversationId);
  // The input stays enabled while Aimo answers so focus never leaves it; only
  // sending is held back when there is no queue to put the message in.
  const disabled = voice.active;
  const sendBlocked = Boolean(busy) && !canQueue;
  // One action at a time: send while there is a draft or attachment, otherwise voice.
  const hasDraft = Boolean(text.trim()) || attachments.length > 0;
  const canRetry = Boolean(error) && hasDraft && !busy;
  function handleComposerKeyDown(
    event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) {
    // Enter sends; Shift+Enter keeps a new line. Ignore Enter that confirms IME input.
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    )
      return;
    event.preventDefault();
    if (!hasDraft || disabled || sendBlocked || reading) return;
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
    ? canQueue
      ? "Queue message"
      : "Working…"
    : canRetry
      ? "Retry request"
      : "Send Order Request";
  return (
    <form
      onSubmit={(event) => {
        if (reading || disabled || sendBlocked) event.preventDefault();
        else void onSubmit(event);
        focusInput();
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
      {queue && queue.length > 0 && (
        <ol aria-label="Queued messages" className="flex flex-col gap-space-xs">
          {queue.map((item, index) => (
            <li
              key={item.id}
              className="flex min-w-0 items-center gap-space-sm rounded-lg border border-border-subtle bg-surface-pure py-space-xs pl-space-sm pr-space-xs text-body-sm text-on-surface"
            >
              <Icon
                name="schedule"
                className="shrink-0 text-[18px] text-secondary"
              />
              <span className="min-w-0 flex-1 truncate" title={item.text}>
                {item.text ||
                  `${item.attachments.length} file${item.attachments.length === 1 ? "" : "s"}`}
              </span>
              {item.text && item.attachments.length > 0 && (
                <span className="shrink-0 text-label-sm text-secondary">
                  +{item.attachments.length} file
                  {item.attachments.length === 1 ? "" : "s"}
                </span>
              )}
              {queuePaused && !busy && index === 0 && onSendQueued && (
                <button
                  type="button"
                  aria-label={`Send queued message: ${item.text || "attachments"}`}
                  title="Send now"
                  onClick={() => {
                    onSendQueued(item.id);
                    focusInput();
                  }}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-primary-container transition-colors hover:bg-surface-container-low focus-visible:outline-2 focus-visible:outline-primary-container"
                >
                  <Icon name="arrow_upward" className="text-[18px]" />
                </button>
              )}
              <button
                type="button"
                aria-label={`Remove queued message: ${item.text || "attachments"}`}
                title="Remove from queue"
                onClick={() => {
                  onRemoveQueued?.(item.id);
                  focusInput();
                }}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-secondary transition-colors hover:bg-surface-container-low hover:text-on-surface focus-visible:outline-2 focus-visible:outline-primary-container"
              >
                <Icon name="close" className="text-[18px]" />
              </button>
            </li>
          ))}
        </ol>
      )}
      {queuePaused && !busy && Boolean(queue?.length) && (
        <p className="px-space-sm text-label-sm text-secondary" role="status">
          Queue paused. Send the next message when you are ready.
        </p>
      )}
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
      {busy && !home && (
        <div className="flex flex-wrap items-center gap-space-sm px-space-sm">
          <button
            type="button"
            onClick={() => onCancel?.()}
            disabled={!onCancel}
            className="rounded-lg bg-surface-pure px-space-md py-space-xs font-label text-label-md font-bold text-primary shadow-sm transition-colors hover:enabled:bg-surface-container-high focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <p className="text-label-sm text-secondary" role="status">
            {canQueue
              ? "Press Escape to cancel · Enter queues your next message"
              : "Press Escape to cancel"}
          </p>
        </div>
      )}
      {canRetry && !home && (
        <div className="flex flex-wrap items-center gap-space-sm px-space-sm">
          <button
            type="submit"
            disabled={reading}
            className="rounded-lg bg-primary-container px-space-md py-space-xs font-label text-label-md font-bold text-on-primary transition-colors hover:enabled:bg-deep-ocean-navy focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container disabled:cursor-not-allowed disabled:opacity-50"
          >
            Retry request
          </button>
          <p className="text-label-sm text-secondary" role="status">
            Your draft is ready to send again.
          </p>
        </div>
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
            : "flex w-full min-w-0 items-end gap-space-sm"
        }
      >
        <label htmlFor="purchase-message" className="sr-only">
          {conversationId
            ? "Continue the conversation"
            : "Your meal or purchasing request"}
        </label>
        <textarea
          ref={inputRef}
          id="purchase-message"
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
          onKeyDown={handleComposerKeyDown}
          maxLength={4000}
          placeholder={
            home ? "Tell Aimo what you need…" : MOCK.request.composerPlaceholder
          }
          className={
            home
              ? "focus:outline-none focus-visible:outline-none"
              : "min-h-11 min-w-0 flex-1 resize-none rounded-lg bg-transparent p-space-sm font-body text-body-md text-on-surface placeholder:text-outline focus:outline-none focus-visible:outline-none"
          }
          disabled={disabled}
          rows={2}
        />
        <div
          className={
            home
              ? "home-composer-actions w-full"
              : "flex shrink-0 items-center gap-space-xs pb-0.5"
          }
        >
          {hasDraft && !(canRetry && !home) ? (
            <button
              type="submit"
              aria-label={sendLabel}
              title={sendLabel}
              disabled={disabled || sendBlocked || reading}
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
          ) : !hasDraft ? (
            <button
              type="button"
              aria-label="Start voice mode"
              title="Start voice mode"
              onClick={() => voice.start(conversationId)}
              disabled={disabled || Boolean(busy) || reading}
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
          ) : null}
        </div>
      </div>
    </form>
  );
}
