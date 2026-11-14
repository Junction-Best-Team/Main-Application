import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { Conversation, ConversationList } from "./types";
import { Badge, ErrorMessage, currency, dateTime, purchaseStatus } from "./shared";
import { store, FakeApiError } from "./store";
import { useStoreState } from "./useStoreState";
import { OverviewPanel } from "./OverviewPanel";

export function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { session, scenario } = useStoreState();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [conversations, setConversations] = useState<ConversationList | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  const activeConversation = useRef(conversationId);
  activeConversation.current = conversationId;

  const loadList = useCallback(async () => {
    try {
      setConversations(await store.listConversations());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void loadList();
  }, [loadList, conversationId]);

  useEffect(() => {
    setConversation(null);
    setError("");
    if (!conversationId) {
      setText("");
      return;
    }
    setLoading(true);
    store
      .getConversation(conversationId)
      .then((data) => {
        if (activeConversation.current !== conversationId) return;
        setConversation(data);
        setText(data.retry_message?.text ?? "");
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [conversationId]);

  useEffect(() => {
    transcript.current?.scrollIntoView({ block: "end", behavior: "instant" });
  }, [conversation?.messages.length, conversation?.busy]);

  async function send(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!text.trim() || sending || conversation?.busy) return;
    setSending(true);
    setError("");
    const messageText = text.trim();
    const id = conversationId ?? null;
    try {
      const result = await store.sendMessage(id, messageText);
      if (!id) {
        navigate(`/conversations/${result.id}`, { replace: true });
      }
      if (activeConversation.current === (id ?? result.id) || !id) {
        setConversation(result);
        setText("");
      }
      await loadList();
    } catch (e) {
      const message = e instanceof FakeApiError ? e.message : (e as Error).message;
      setError(message);
      if (id) {
        try {
          const reloaded = await store.getConversation(id);
          if (activeConversation.current === id) setConversation(reloaded);
        } catch {
          /* Keep the actionable send error. */
        }
      }
    } finally {
      setSending(false);
    }
  }

  const busy = sending || conversation?.busy;

  return (
    <main className="chat-workspace">
      <aside className="conversation-sidebar" aria-label="Conversations">
        <Link className="new-conversation" to="/request">
          New purchase
        </Link>
        <h2>Your conversations</h2>
        {!conversations ? (
          <p className="muted small">Loading conversations…</p>
        ) : conversations.items.length === 0 ? (
          <p className="muted small">Start with a meal or an ingredient list.</p>
        ) : (
          <ul>
            {conversations.items.map((item) => (
              <li key={item.id}>
                <Link to={`/conversations/${item.id}`} aria-current={conversationId === item.id ? "page" : undefined}>
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
        )}
        <Link className="history-link" to="/purchases">
          View purchase history
        </Link>
      </aside>
      <section className="conversation-main">
        <div className="chat-heading">
          <h1>{conversation?.title || (conversationId ? "Your conversation" : "What are we cooking?")}</h1>
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
                onClick={() => setText("I need ingredients for 200 portions of carbonara.")}
              >
                I need ingredients for 200 portions of carbonara.
              </button>
              <p className="muted small">
                We’ll clarify the details, check actual catalog products and show the exact purchase for your
                confirmation.
              </p>
            </div>
          </div>
        )}
        <div className="transcript" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions">
          {conversation?.messages.map((message) => (
            <article className={`chat-message ${message.role}`} key={message.id}>
              <div className="message-byline">
                <strong>{message.role === "user" ? "You" : "Aimo"}</strong>
                <time dateTime={message.created_at}>{dateTime(message.created_at)}</time>
              </div>
              <p className="message-text">{message.text}</p>
              {message.meal_plan && (
                <section className="meal-plan" aria-label="Proposed meal plan">
                  <h2>{message.meal_plan.title}</h2>
                  <p>{message.meal_plan.portions} portions</p>
                  <ul>
                    {message.meal_plan.ingredients.map((ingredient, i) => (
                      <li key={i}>
                        <span>{ingredient.name}</span>
                        <strong>
                          {ingredient.amount} {ingredient.unit}
                        </strong>
                      </li>
                    ))}
                  </ul>
                  {(message.meal_plan.notes ?? []).map((note, i) => (
                    <p className="muted small" key={i}>
                      {note}
                    </p>
                  ))}
                  <p className="muted small">
                    Recipe quantities are a proposal. Verified quantities and purchasing checks appear in the
                    basket.
                  </p>
                </section>
              )}
              {message.proposal_id && (
                <Link className="basket-link" to={`/purchases/${message.proposal_id}`}>
                  Review basket and purchasing checks
                </Link>
              )}
            </article>
          ))}
          {busy && (
            <p className="agent-working" role="status">
              Aimo is checking your request… You can return to this conversation.
            </p>
          )}
          <div ref={transcript} />
        </div>
        {Boolean(conversation?.purchases.length) && (
          <section className="conversation-baskets" aria-label="Conversation baskets">
            <h2>Baskets in this conversation</h2>
            {conversation?.purchases.map((purchase) => (
              <Link key={purchase.proposal_id} to={`/purchases/${purchase.proposal_id}`}>
                <span>{purchase.request.request_id}</span>
                <Badge value={purchaseStatus(purchase)} />
                <strong>{currency(purchase.snapshot.gross_total)}</strong>
              </Link>
            ))}
          </section>
        )}
        <form className="chat-composer" onSubmit={send}>
          <label htmlFor="purchase-message">
            {conversationId ? "Continue the conversation" : "Your meal or purchasing request"}
          </label>
          <textarea
            id="purchase-message"
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={3}
            maxLength={4000}
            placeholder="A meal, the number of portions, dietary needs…"
            disabled={Boolean(busy)}
            required
          />
          <div className="composer-footer">
            <p className="muted small">
              Messages never authorize a purchase. You confirm the exact basket separately.
            </p>
            <button className="primary" disabled={Boolean(busy) || !text.trim()}>
              {busy ? "Working…" : error && text ? "Retry request" : "Send request"}
            </button>
          </div>
        </form>
        {scenario === "reconnecting" && (
          <p className="muted small" role="status">
            Reconnecting to updates. Your conversation is saved; refresh to check the latest state.
          </p>
        )}
        <p className="chat-demo-note">
          Demo ordering only. No real supplier orders or stock reservations. Signed in as {session?.buyer_id}.
        </p>
      </section>
      <OverviewPanel conversation={conversation} />
    </main>
  );
}
