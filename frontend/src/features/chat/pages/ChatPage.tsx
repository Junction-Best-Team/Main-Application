import { Link, useParams } from "react-router-dom";
import { Badge } from "../../../shared/components/Badge";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { currency } from "../../../shared/lib/format";
import { getPurchaseStatus } from "../../purchases/model/purchaseStatus";
import { useChat } from "../hooks/useChat";
import { ConversationSidebar } from "../components/ConversationSidebar";
import { ConversationTranscript } from "../components/ConversationTranscript";
import { ChatComposer } from "../components/ChatComposer";
export function ChatPage() {
  const { conversationId } = useParams();
  const {
    conversation,
    conversations,
    text,
    setText,
    error,
    loading,
    reconnecting,
    loadingOlder,
    loadOlder,
    transcript,
    send,
    busy,
  } = useChat(conversationId);
  return (
    <main className="chat-workspace mx-auto grid w-full max-w-[1600px] grid-cols-1 md:grid-cols-[224px_minmax(0,1fr)]">
      <ConversationSidebar
        conversations={conversations}
        conversationId={conversationId}
        loadingOlder={loadingOlder}
        loadOlder={loadOlder}
      />
      <section className="conversation-main mx-auto flex w-full min-w-0 max-w-[1100px] flex-col gap-6 p-4 md:p-8 lg:p-10">
        <div className="chat-heading border-b border-border-subtle pb-6 [&_h1]:wrap-anywhere [&_h1]:text-headline-lg-mobile md:[&_h1]:text-headline-lg [&_p]:mb-0 [&_p]:text-secondary">
          <h1>
            {conversation?.title ||
              (conversationId ? "Your conversation" : "What are we cooking?")}
          </h1>
          <p>
            {conversationId
              ? "Meal planning and purchasing, in one conversation."
              : "Tell us the meal and how many people. We’ll help build the basket."}
          </p>
        </div>
        <ErrorMessage message={error} />
        {loading && <p role="status">Loading your conversation…</p>}
        {!conversationId && (
          <div className="meal-start flex flex-col items-start gap-5 rounded-xl border border-border-subtle bg-surface-pure p-5 sm:flex-row sm:items-center md:p-6">
            <div
              className="flex size-20 shrink-0 flex-col items-center justify-center rounded-full bg-primary-container font-label text-on-primary [&_span:first-child]:text-[32px] [&_span:first-child]:font-bold [&_span:last-child]:text-label-sm md:size-28"
              aria-hidden="true"
            >
              <span>200</span>
              <span>portions</span>
            </div>
            <div>
              <h2>A menu is a good place to start.</h2>
              <button
                className="rounded border border-border-subtle bg-surface-container-low px-4 py-3 text-left font-semibold text-primary hover:enabled:bg-secondary-container"
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
          </div>
        )}
        <ConversationTranscript
          conversation={conversation}
          busy={busy}
          transcript={transcript}
        />
        {Boolean(conversation?.purchases.length) && (
          <section
            className="conversation-baskets flex flex-col gap-2 [&_h2]:text-headline-sm [&>a]:flex [&>a]:flex-wrap [&>a]:items-center [&>a]:gap-3 [&>a]:rounded-lg [&>a]:border [&>a]:border-border-subtle [&>a]:bg-surface-pure [&>a]:p-4 [&>a]:text-body-sm [&>a:hover]:border-wholesale-teal [&>a:hover]:no-underline [&>a>span:first-child]:min-w-36 [&>a>span:first-child]:flex-1"
            aria-label="Conversation baskets"
          >
            <h2>Baskets in this conversation</h2>
            {conversation?.purchases.map((purchase) => (
              <Link
                key={purchase.proposal_id}
                to={`/purchases/${purchase.proposal_id}`}
              >
                <span>{purchase.request.request_id}</span>
                <Badge value={getPurchaseStatus(purchase)} />
                <strong>{currency(purchase.snapshot.gross_total)}</strong>
              </Link>
            ))}
          </section>
        )}
        <ChatComposer
          conversationId={conversationId}
          text={text}
          onTextChange={setText}
          error={error}
          busy={busy}
          onSubmit={send}
        />
        {reconnecting && (
          <p className="text-body-sm text-secondary" role="status">
            Reconnecting to updates. Your conversation is saved; refresh to
            check the latest state.
          </p>
        )}
        <p className="mt-0 text-body-sm text-secondary">
          Demo ordering only. No real supplier orders or stock reservations.
        </p>
      </section>
    </main>
  );
}
