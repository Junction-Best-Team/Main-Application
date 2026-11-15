import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type { Conversation } from "../../../shared/api/types";
import type { components } from "../../../shared/api/schema";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { copyText } from "../../../shared/lib/copyText";
import { dateTime } from "../../../shared/lib/format";
import { ChatActivity } from "./ChatActivity";
import { MealPlanCard } from "./MealPlanCard";
import { RecipeIllustration } from "./RecipeIllustration";
import { MessageMarkdown } from "./MessageMarkdown";
import { AttachmentCards } from "./AttachmentCards";
import { SystemMessage } from "./SystemMessage";

type ChatMessage = components["schemas"]["ChatMessage"];

const messageActionClassName =
  "flex h-8 w-8 items-center justify-center rounded-full text-secondary transition-colors hover:enabled:bg-surface-container-high hover:enabled:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container disabled:cursor-not-allowed disabled:opacity-40";

export function ConversationTranscript({
  conversation,
  busy,
  stopped = false,
  onReviewBasket,
  onEditMessage,
  onContinue,
}: {
  conversation: Conversation | null;
  busy: boolean;
  /** The customer stopped the latest turn. */
  stopped?: boolean;
  /** Opens the existing Overview / purchase handoff for this proposal. */
  onReviewBasket?: (proposalId: string) => void;
  /** Replace a user message, truncate later turns, and regenerate. */
  onEditMessage?: (messageId: number, text: string) => Promise<void> | void;
  onContinue?: () => void;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  useEffect(() => {
    if (busy) setEditingId(null);
  }, [busy]);
  const plan = conversation?.messages.at(-1)?.meal_plan;
  const unmatched = plan?.ingredients.some(
    (item) =>
      !item.product_id || (plan.recipe_plan_id && item.status !== "matched"),
  );
  return (
    <div
      role="log"
      aria-label="Conversation messages"
      aria-live="polite"
      aria-relevant="additions"
      className="flex flex-col gap-space-lg"
    >
      {conversation?.messages.map((message) =>
        message.role === "system" ? (
          <SystemMessage key={message.id} message={message} />
        ) : message.role === "user" ? (
          <UserMessage
            key={message.id}
            message={message}
            busy={busy}
            editing={editingId === message.id}
            onBeginEdit={() => setEditingId(message.id)}
            onCancelEdit={() => setEditingId(null)}
            onUpdate={async (text) => {
              if (!onEditMessage) return;
              await onEditMessage(message.id, text);
              setEditingId(null);
            }}
          />
        ) : (
          <article
            key={message.id}
            className="flex max-w-3xl items-start gap-space-sm"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-wholesale-teal text-on-primary dark:bg-primary-container shadow-sm">
              <Icon name="smart_toy" className="text-[18px]" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
              <div className="rounded-xl rounded-tl-none bg-surface-container-low p-space-md shadow-sm">
                <div className="text-body-md text-on-surface">
                  <MessageMarkdown text={message.text} />
                </div>
                {message.image && (
                  <RecipeIllustration
                    key={message.image.url}
                    image={message.image}
                  />
                )}
                {message.meal_plan && <MealPlanCard plan={message.meal_plan} />}
                {message.proposal_id && (
                  <>
                    {onReviewBasket &&
                      conversation.purchases.some(
                        (p) =>
                          p.proposal_id === message.proposal_id &&
                          p.order_status !== "accepted_mock",
                      ) && (
                        <div className="mt-space-md flex flex-col items-start gap-space-xs">
                          <button
                            type="button"
                            onClick={() => onReviewBasket(message.proposal_id!)}
                            className="rounded-lg bg-primary-container px-space-md py-space-sm font-label text-label-md font-bold text-on-primary transition-colors hover:bg-deep-ocean-navy focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container"
                          >
                            Review basket to confirm
                          </button>
                          <p className="text-label-sm text-secondary">
                            Sending chat never places an order.
                          </p>
                        </div>
                      )}
                  </>
                )}
              </div>
              <MessageByline who="Aimo" at={message.created_at} />
            </div>
          </article>
        ),
      )}
      <ChatActivity
        activity={conversation?.activity}
        busy={busy}
        stopped={stopped}
        onContinue={unmatched ? onContinue : undefined}
        unmatched={Boolean(unmatched)}
      />
    </div>
  );
}

function UserMessage({
  message,
  busy,
  editing,
  onBeginEdit,
  onCancelEdit,
  onUpdate,
}: {
  message: ChatMessage;
  busy: boolean;
  editing: boolean;
  onBeginEdit: () => void;
  onCancelEdit: () => void;
  onUpdate: (text: string) => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (copiedTimer.current != null) window.clearTimeout(copiedTimer.current);
    },
    [],
  );
  return (
    <article className="group ml-auto flex max-w-2xl flex-row-reverse items-start gap-space-sm">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary dark:bg-primary-container shadow-sm">
        <Icon name="person" className="text-[18px]" />
      </div>
      <div className="flex min-w-0 flex-col items-end gap-space-xs">
        <AttachmentCards files={message.attachments ?? []} />
        {editing ? (
          <UserMessageEditor
            original={message.text}
            onCancel={onCancelEdit}
            onUpdate={onUpdate}
          />
        ) : (
          <>
            {message.text && (
              <div className="max-w-full rounded-xl rounded-tr-none bg-primary dark:bg-primary-container px-space-md py-space-sm text-body-md text-on-primary shadow-sm">
                <MessageMarkdown text={message.text} />
              </div>
            )}
            <div className="flex items-center gap-space-xs opacity-100 transition-opacity [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:focus-within:opacity-100 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:group-focus-within:opacity-100">
              <button
                type="button"
                className={messageActionClassName}
                aria-label={copied ? "Copied" : "Copy message"}
                title={copied ? "Copied" : "Copy"}
                onClick={() => {
                  void copyText(message.text).then((ok) => {
                    if (!ok) return;
                    setCopied(true);
                    if (copiedTimer.current != null)
                      window.clearTimeout(copiedTimer.current);
                    copiedTimer.current = window.setTimeout(
                      () => setCopied(false),
                      2000,
                    );
                  });
                }}
              >
                <Icon
                  name={copied ? "check" : "content_copy"}
                  className="text-[18px]"
                />
              </button>
              <button
                type="button"
                className={messageActionClassName}
                aria-label="Edit message"
                title="Edit"
                disabled={busy}
                aria-disabled={busy}
                onClick={() => {
                  if (busy) return;
                  onBeginEdit();
                }}
              >
                <Icon name="edit" className="text-[18px]" />
              </button>
            </div>
          </>
        )}
        <MessageByline who="You" at={message.created_at} />
      </div>
    </article>
  );
}

function UserMessageEditor({
  original,
  onCancel,
  onUpdate,
}: {
  original: string;
  onCancel: () => void;
  onUpdate: (text: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(original);
  const [saving, setSaving] = useState(false);
  const areaRef = useRef<HTMLTextAreaElement | null>(null);
  const labelId = useId();
  const unchanged = draft === original;
  const empty = !draft.trim();
  const updateDisabled = saving || empty || unchanged;

  function grow(area: HTMLTextAreaElement | null) {
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
  }

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    area.focus();
    const end = area.value.length;
    area.setSelectionRange(end, end);
    grow(area);
  }, []);

  async function submit() {
    if (updateDisabled) return;
    setSaving(true);
    try {
      await onUpdate(draft);
    } finally {
      setSaving(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onCancel();
      return;
    }
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    )
      return;
    event.preventDefault();
    void submit();
  }

  return (
    <div
      data-message-edit="true"
      className="flex w-full min-w-[min(100%,20rem)] max-w-full flex-col items-end gap-space-sm"
    >
      <label id={labelId} className="sr-only">
        Edit message
      </label>
      <textarea
        ref={areaRef}
        aria-labelledby={labelId}
        value={draft}
        maxLength={4000}
        rows={1}
        onChange={(event) => {
          setDraft(event.target.value);
          grow(event.target);
        }}
        onKeyDown={onKeyDown}
        className="w-full resize-none rounded-[24px] bg-primary px-space-md py-space-sm font-body text-body-md text-on-primary shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container dark:bg-primary-container"
      />
      <div className="flex items-center gap-space-sm">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg px-space-md py-space-sm font-label text-label-md text-secondary transition-colors hover:bg-surface-container-high focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={updateDisabled}
          aria-disabled={updateDisabled}
          className="rounded-lg bg-primary-container px-space-md py-space-sm font-label text-label-md font-bold text-on-primary transition-colors hover:enabled:bg-deep-ocean-navy focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container disabled:cursor-not-allowed disabled:opacity-50"
        >
          Update
        </button>
      </div>
    </div>
  );
}

function MessageByline({ who, at }: { who: string; at: string }) {
  return (
    <span className="mt-1 font-label text-label-sm text-secondary">
      {who} • <time dateTime={at}>{dateTime(at)}</time>
    </span>
  );
}
