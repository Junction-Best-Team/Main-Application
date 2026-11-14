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
    <main className="chat-workspace">
      <ConversationSidebar
        conversations={conversations}
        conversationId={conversationId}
        loadingOlder={loadingOlder}
        loadOlder={loadOlder}
      />
      <section className="conversation-main">
        <div className="chat-heading">
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
          <div className="meal-start">
            <div className="meal-illustration" aria-hidden="true">
              <span>200</span>
              <span>portions</span>
            </div>
            <div>
              <h2>A menu is a good place to start.</h2>
              <button
                className="example-request"
                onClick={() =>
                  setText("I need ingredients for 200 portions of carbonara.")
                }
              >
                I need ingredients for 200 portions of carbonara.
              </button>
              <p className="muted small">
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
            className="conversation-baskets"
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
          <p className="muted small" role="status">
            Reconnecting to updates. Your conversation is saved; refresh to
            check the latest state.
          </p>
        )}
        <p className="chat-demo-note">
          Demo ordering only. No real supplier orders or stock reservations.
        </p>
      </section>
    </main>
  );
}
