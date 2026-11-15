import { KitchenPattern } from "../../../shared/components/KitchenPattern";
import { useEffect, useLayoutEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge } from "../../../shared/components/Badge";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { currency } from "../../../shared/lib/format";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useAuth } from "../../auth/useAuth";
import { getPurchaseStatus } from "../../purchases/model/purchaseStatus";
import { StagedOverview } from "../../purchases/components/StagedOverview";
import { useChat } from "../hooks/useChat";
import { useVoiceMode } from "../hooks/useVoiceMode";
import { ConversationTranscript } from "../components/ConversationTranscript";
import { ChatComposer } from "../components/ChatComposer";
import {
  finishChatExpansion,
  hasChatExpansion,
} from "../../home/model/expandToChat";
export function ChatPage() {
  const { conversationId } = useParams();
  const [selection, setSelection] = useState<{
    conversationId?: string;
    proposalId: string;
  } | null>(null);
  const { session } = useAuth();
  // Arriving from Home's expand animation: fade the chat in over the expanded card.
  const [entering] = useState(hasChatExpansion);
  useLayoutEffect(() => {
    if (entering) finishChatExpansion();
  }, [entering]);
  const {
    conversation,
    text,
    setText,
    attachments,
    setAttachments,
    error,
    errorDebug,
    loading,
    reconnecting,
    messageViewport,
    send,
    cancel,
    busy,
    queue,
    queuePaused,
    removeQueued,
    sendQueued,
    reload,
  } = useChat(conversationId);
  // The voice orb floats over the end of the history: make room and keep the latest in view.
  const voiceOpen = useVoiceMode().state !== null;
  useEffect(() => {
    const viewport = messageViewport.current;
    if (voiceOpen && viewport)
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
  }, [voiceOpen, messageViewport]);
  return (
    <main
      className={`chat-page isolate ${entering ? "chat-enter " : ""}mx-auto flex min-h-0 w-full max-w-[1720px] flex-1 flex-col gap-space-md p-margin-sm lg:flex-row lg:items-stretch md:gap-space-lg lg:gap-0 md:p-space-lg ${conversation?.purchases.length ? "pb-28 md:pb-28 lg:pb-space-lg" : ""}`}
    >
      {/* Kitchen tools behind the page, cut away around the assistant heading. */}
      <KitchenPattern seed={5} avoid="[data-pattern-avoid]" />
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col gap-space-sm md:gap-space-md">
        <header
          data-pattern-avoid
          className="flex shrink-0 items-center gap-space-md [@media(max-height:650px)]:hidden"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary-container text-on-primary shadow-sm">
            <Icon name="smart_toy" className="text-[26px]" />
          </div>
          <div className="min-w-0">
            <h1 className="font-headline text-headline-sm tracking-tight text-primary md:text-headline-md">
              Aimo Kitchen Assistant
            </h1>
            <p className="hidden text-body-sm text-secondary md:block">
              {MOCK.request.assistantSubtitle}
            </p>
          </div>
        </header>

        <div className="chat-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-surface-pure shadow-[0_-4px_14px_-6px_rgba(30,61,72,0.22),0_1px_2px_rgba(0,0,0,0.05)] dark:shadow-sm">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-space-md gap-y-space-xs bg-surface-container-low px-space-md py-space-sm">
            <div className="flex min-w-0 flex-1 items-center gap-space-xs">
              <Icon
                name="restaurant_menu"
                className="text-[18px] text-wholesale-teal"
              />
              <span className="truncate font-label text-label-md text-primary">
                {conversation?.title ?? session?.buyer_id}
              </span>
            </div>
          </div>

          {/* Contain absolute screen-reader labels within the scrolling history. */}
          <div
            ref={messageViewport}
            role="region"
            aria-label="Conversation history"
            tabIndex={0}
            className="relative flex min-h-0 flex-1 flex-col gap-space-lg overflow-y-auto overscroll-contain p-space-md md:p-space-lg"
          >
            <p className="shrink-0 text-label-sm text-secondary">
              Demo ordering only. No real supplier orders or stock reservations.
              Signed in as {session?.buyer_id}.
            </p>
            <ErrorMessage message={error} debug={errorDebug} />
            {loading && <p role="status">Loading your conversation…</p>}
            {!conversationId && (
              <div className="flex flex-col items-start gap-space-sm rounded-xl bg-surface-container-low p-space-md">
                <h2 className="font-headline text-headline-sm text-primary">
                  A menu is a good place to start.
                </h2>
                <button
                  type="button"
                  className="rounded-lg bg-surface-pure px-space-md py-space-sm text-left text-body-sm font-bold text-primary shadow-sm"
                  onClick={() =>
                    setText("I need ingredients for 200 portions of carbonara.")
                  }
                >
                  I need ingredients for 200 portions of carbonara.
                </button>
                <p className="text-body-sm text-secondary">
                  We’ll clarify the details, check actual catalog products and
                  show the exact purchase for your confirmation.
                </p>
              </div>
            )}
            <ConversationTranscript
              conversation={conversation}
              busy={busy}
              onReviewBasket={(proposalId) =>
                setSelection({ conversationId, proposalId })
              }
            />

            {Boolean(conversation?.purchases.length) && (
              <section
                aria-label="Conversation baskets"
                className="flex flex-col gap-space-xs"
              >
                <h2 className="font-label text-label-md uppercase tracking-wider text-secondary">
                  Baskets in this conversation
                </h2>
                {conversation?.purchases.map((purchase) => {
                  const row = (
                    <>
                      <span className="min-w-36 flex-1">
                        {purchase.request.request_id}
                      </span>
                      <Badge value={getPurchaseStatus(purchase)} />
                      <strong className="text-primary">
                        {currency(purchase.snapshot.gross_total)}
                      </strong>
                    </>
                  );
                  const rowClass =
                    "flex flex-wrap items-center gap-space-md rounded-lg bg-surface-container-low px-space-md py-space-sm text-body-sm";
                  // Only placed orders link to Past Orders; open baskets are decided in the Overview panel.
                  return purchase.order_status === "accepted_mock" ? (
                    <Link
                      key={purchase.proposal_id}
                      to={`/purchases/${purchase.proposal_id}`}
                      className={rowClass}
                    >
                      {row}
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        setSelection({
                          conversationId,
                          proposalId: purchase.proposal_id,
                        })
                      }
                      key={purchase.proposal_id}
                      className={rowClass}
                    >
                      {row}
                    </button>
                  );
                })}
              </section>
            )}
            {reconnecting && (
              <p className="text-body-sm text-secondary" role="status">
                Reconnecting to updates. Your conversation is saved; refresh to
                check the latest state.
              </p>
            )}
            {voiceOpen && <div aria-hidden="true" className="h-24 shrink-0" />}
          </div>

          <ChatComposer
            key={conversationId ?? "new"}
            conversationId={conversationId}
            text={text}
            onTextChange={setText}
            attachments={attachments}
            onAttachmentsChange={setAttachments}
            error={error}
            busy={busy}
            onSubmit={send}
            queue={queue}
            queuePaused={queuePaused}
            onRemoveQueued={removeQueued}
            onSendQueued={sendQueued}
            onCancel={() => void cancel()}
          />
        </div>
      </div>
      {/* Overview: right-hand column on desktop, fixed bottom drawer on mobile. */}
      <StagedOverview
        conversation={conversation}
        onPrepared={(prepared) => {
          setSelection({ conversationId, proposalId: prepared.proposal_id });
          void reload();
        }}
        selectedId={
          selection?.conversationId === conversationId
            ? selection?.proposalId
            : undefined
        }
      />
    </main>
  );
}
