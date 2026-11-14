import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import type { components } from "./api-types";
import "./style.css";

type Session = components["schemas"]["SessionResponse"];
type Proposal = components["schemas"]["ProposalResponse"];
type Inbox = components["schemas"]["InboxResponse"];
type Conversation = components["schemas"]["ConversationResponse"];
type ConversationList = components["schemas"]["ConversationList"];
type Commit = components["schemas"]["CommitResponse"];
const Auth = createContext<{
  session: Session | null;
  setSession: (s: Session | null) => void;
}>({ session: null, setSession: () => {} });
class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new ApiError(
      r.status,
      body.error?.message ||
        (r.status === 422
          ? "Check the submitted values."
          : "The service could not complete this request. Try again."),
    );
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
const currency = (value: string | null | undefined, unit = "EUR") =>
  value == null
    ? "Unresolved"
    : new Intl.NumberFormat("en-FI", {
        style: "currency",
        currency: unit,
      }).format(Number(value));
const dateTime = (value: string) =>
  new Intl.DateTimeFormat("en-FI", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Helsinki",
  }).format(new Date(value));
const title = (status: string) =>
  status.replaceAll("_", " ").replace(/^./, (s) => s.toUpperCase());
function status(p: Proposal) {
  if (p.approval_status === "superseded") return "superseded";
  if (p.order_status === "accepted_mock") return "accepted_mock";
  if (p.approval_status === "rejected") return "rejected";
  if (new Date(p.expires_at) <= new Date()) return "expired";
  return p.approval_status === "not_required"
    ? p.policy_outcome
    : p.approval_status;
}
function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{title(value)}</span>;
}
function ErrorMessage({ message }: { message: string }) {
  return message ? (
    <div className="error" role="alert">
      {message}
    </div>
  ) : null;
}

function Login() {
  const { session, setSession } = useContext(Auth);
  const location = useLocation();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const next = (location.state as { from?: string } | null)?.from;
  const destination =
    typeof next === "string" &&
    (next === "/" || /^\/(approvals|purchases|conversations)(\/|$)/.test(next))
      ? next
      : "/";
  if (session) return <Navigate to={destination} replace />;
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const s = await api<Session>("/api/login", {
        method: "POST",
        body: JSON.stringify({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      setSession(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-layout">
      <section className="welcome">
        <span className="brand large">
          aimo<span className="brand-dot">.</span>
        </span>
        <h1>
          From the menu
          <br />
          to your basket.
        </h1>
        <p>
          Plan a meal, find ingredients and review real catalog matches. You
          confirm the exact basket before a demo order is recorded.
        </p>
        <div className="welcome-note">
          Your conversations, decisions and purchase history stay together.
        </div>
      </section>
      <section className="login-panel">
        <h2>Buyer sign in</h2>
        <p>Use your preconfigured buyer account.</p>
        <form onSubmit={submit}>
          <label>
            Username
            <input name="username" autoComplete="username" required autoFocus />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <ErrorMessage message={error} />
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted small">
          Demo purchasing service. No real supplier orders or stock
          reservations.
        </p>
      </section>
    </main>
  );
}

function useRefresh(load: () => Promise<void>, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      if (active && document.visibilityState === "visible") await load();
      if (active) timer = setTimeout(tick, 30000);
    }
    timer = setTimeout(tick, 30000);
    const visibility = () => {
      if (document.visibilityState === "visible") {
        clearTimeout(timer);
        void tick();
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      active = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [load, enabled]);
}

function ChatPage() {
  const { conversationId } = useParams();
  const { session, setSession } = useContext(Auth);
  const navigate = useNavigate();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [conversations, setConversations] = useState<ConversationList | null>(
    null,
  );
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const sendingRef = useRef(false);
  const createKey = useRef(crypto.randomUUID());
  const transcript = useRef<HTMLDivElement>(null);
  const loadedConversation = useRef<string | null>(null);
  const activeConversation = useRef(conversationId);
  activeConversation.current = conversationId;
  const pendingStorage = `aimo-pending-${session?.buyer_id}-${conversationId}`;
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    },
    [setSession],
  );
  const loadList = useCallback(async () => {
    try {
      setConversations(
        await api<ConversationList>("/api/conversations?limit=30"),
      );
    } catch (e) {
      fail(e);
    }
  }, [fail]);
  async function loadOlder() {
    if (conversations?.next_offset == null || loadingOlder) return;
    setLoadingOlder(true);
    try {
      const older = await api<ConversationList>(
        `/api/conversations?limit=30&offset=${conversations.next_offset}`,
      );
      setConversations((current) =>
        current
          ? {
              ...older,
              items: [
                ...current.items,
                ...older.items.filter(
                  (item) =>
                    !current.items.some((existing) => existing.id === item.id),
                ),
              ],
            }
          : older,
      );
    } catch (e) {
      fail(e);
    } finally {
      setLoadingOlder(false);
    }
  }
  const load = useCallback(async () => {
    if (!conversationId) return;
    try {
      const data = await api<Conversation>(
        `/api/conversations/${conversationId}`,
      );
      if (activeConversation.current !== conversationId) return;
      setConversation(data);
      if (loadedConversation.current !== conversationId) {
        loadedConversation.current = conversationId;
        if (data.retry_message && !sendingRef.current)
          setText(data.retry_message.text);
      }
      setReconnecting(false);
    } catch (e) {
      fail(e);
    }
  }, [conversationId, fail]);
  useEffect(() => {
    void loadList();
  }, [loadList, conversationId]);
  useEffect(() => {
    setConversation(null);
    loadedConversation.current = null;
    setError("");
    const saved = sessionStorage.getItem(pendingStorage);
    try {
      setText(saved ? JSON.parse(saved).text : "");
    } catch {
      setText("");
    }
    if (!conversationId) return;
    setLoading(true);
    void load().finally(() => setLoading(false));
  }, [conversationId, load, pendingStorage]);
  useRefresh(load, Boolean(conversationId));
  useEffect(() => {
    if (!conversationId) return;
    let stream: EventSource | null = null;
    const open = () => {
      stream?.close();
      stream = null;
      if (document.visibilityState !== "visible") return;
      stream = new EventSource(`/api/conversations/${conversationId}/events`);
      stream.addEventListener("conversation", (event) => {
        if (activeConversation.current !== conversationId) return;
        try {
          setConversation(JSON.parse((event as MessageEvent).data));
          setReconnecting(false);
        } catch {
          void load();
        }
      });
      stream.addEventListener("expired", () => setSession(null));
      stream.onerror = () => setReconnecting(true);
    };
    open();
    document.addEventListener("visibilitychange", open);
    return () => {
      stream?.close();
      document.removeEventListener("visibilitychange", open);
    };
  }, [conversationId, load]);
  useEffect(() => {
    transcript.current?.scrollIntoView({ block: "end", behavior: "instant" });
  }, [conversation?.messages.length, conversation?.busy]);
  async function send(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!text.trim() || !session || sendingRef.current || conversation?.busy)
      return;
    sendingRef.current = true;
    setSending(true);
    setError("");
    const messageText = text.trim();
    let id = conversationId;
    try {
      if (!id) {
        const created = await api<Conversation>("/api/conversations", {
          method: "POST",
          headers: { "X-CSRF-Token": session.csrf_token },
          body: JSON.stringify({
            title: messageText.slice(0, 120),
            idempotency_key: createKey.current,
          }),
        });
        id = created.id;
        setConversation(created);
        createKey.current = crypto.randomUUID();
        navigate(`/conversations/${id}`, { replace: true });
      }
      const storageKey = `aimo-pending-${session.buyer_id}-${id}`;
      let key: string = crypto.randomUUID();
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
        if (saved?.text === messageText) key = saved.idempotency_key;
      } catch {
        /* A missing pending request starts a new turn. */
      }
      if (conversation?.retry_message?.text === messageText) {
        key = conversation.retry_message.idempotency_key;
      }
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({ text: messageText, idempotency_key: key }),
      );
      const result = await api<Conversation>(
        `/api/conversations/${id}/messages`,
        {
          method: "POST",
          headers: { "X-CSRF-Token": session.csrf_token },
          body: JSON.stringify({ text: messageText, idempotency_key: key }),
        },
      );
      sessionStorage.removeItem(storageKey);
      if (activeConversation.current === id) {
        setConversation(result);
        setText("");
      }
      await loadList();
    } catch (e) {
      if (activeConversation.current !== id) return;
      fail(e);
      setText(messageText);
      if (id) {
        try {
          const result = await api<Conversation>(`/api/conversations/${id}`);
          if (activeConversation.current === id) setConversation(result);
        } catch {
          /* Keep the actionable send error. */
        }
      }
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }
  useEffect(() => {
    if (conversation?.retry_message && !conversation.busy && !sending) {
      setText(conversation.retry_message.text);
      setError("The response was interrupted. Retry this request to continue.");
    }
  }, [conversation?.retry_message?.idempotency_key, conversation?.busy, sending]);
  const busy = sending || conversation?.busy;
  return (
    <main className="chat-workspace">
      <aside className="conversation-sidebar" aria-label="Conversations">
        <Link className="new-conversation" to="/">
          New purchase
        </Link>
        <h2>Your conversations</h2>
        {!conversations ? (
          <p className="muted small">Loading conversations…</p>
        ) : conversations.items.length === 0 ? (
          <p className="muted small">
            Start with a meal or an ingredient list.
          </p>
        ) : (
          <ul>
            {conversations.items.map((item) => (
              <li key={item.id}>
                <Link
                  to={`/conversations/${item.id}`}
                  aria-current={conversationId === item.id ? "page" : undefined}
                >
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {conversations?.next_offset != null && (
          <button
            className="older-conversations"
            onClick={loadOlder}
            disabled={loadingOlder}
          >
            {loadingOlder ? "Loading…" : "Older conversations"}
          </button>
        )}
        <Link className="history-link" to="/purchases">
          View purchase history
        </Link>
      </aside>
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
        <div
          className="transcript"
          aria-label="Conversation messages"
          aria-live="polite"
          aria-relevant="additions"
        >
          {conversation?.messages.map((message) => (
            <article
              className={`chat-message ${message.role}`}
              key={message.id}
            >
              <div className="message-byline">
                <strong>{message.role === "user" ? "You" : "Aimo"}</strong>
                <time dateTime={message.created_at}>
                  {dateTime(message.created_at)}
                </time>
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
                          {ingredient.amount == null
                            ? "Quantity unresolved"
                            : `${ingredient.amount} ${ingredient.unit}`}
                        </strong>
                        {ingredient.status === "unresolved" && (
                          <p>{ingredient.reason}</p>
                        )}
                        {ingredient.product_id && (
                          <p>Product: {ingredient.product_id}</p>
                        )}
                        {ingredient.conversion?.sales_quantity && (
                          <p>
                            Buy {String(ingredient.conversion.sales_quantity)}{" "}
                            {String(ingredient.conversion.sales_unit)}
                            {Number(ingredient.conversion.excess) > 0 &&
                              ` · Excess: ${ingredient.conversion.excess} ${ingredient.unit}`}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                  {message.meal_plan.attribution && (
                    <p className="muted small">
                      {message.meal_plan.attribution}
                    </p>
                  )}
                  {(message.meal_plan.notes ?? []).map((note, i) => (
                    <p className="muted small" key={i}>
                      {note}
                    </p>
                  ))}
                  <p className="muted small">
                    Recipe quantities are a proposal. Verified quantities and
                    purchasing checks appear in the basket.
                  </p>
                </section>
              )}
              {message.proposal_id && (
                <Link
                  className="basket-link"
                  to={`/purchases/${message.proposal_id}`}
                >
                  Review basket and purchasing checks
                </Link>
              )}
            </article>
          ))}
          {busy && (
            <p className="agent-working" role="status">
              Aimo is checking your request… You can return to this
              conversation.
            </p>
          )}
          <div ref={transcript} />
        </div>
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
                <Badge value={status(purchase)} />
                <strong>{currency(purchase.snapshot.gross_total)}</strong>
              </Link>
            ))}
          </section>
        )}
        <form className="chat-composer" onSubmit={send}>
          <label htmlFor="purchase-message">
            {conversationId
              ? "Continue the conversation"
              : "Your meal or purchasing request"}
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
              Messages never authorize a purchase. You confirm the exact basket
              separately.
            </p>
            <button
              className="primary"
              disabled={Boolean(busy) || !text.trim()}
            >
              {busy
                ? "Working…"
                : error && text
                  ? "Retry request"
                  : "Send request"}
            </button>
          </div>
        </form>
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

function PurchasesPage() {
  const { setSession } = useContext(Auth);
  const [data, setData] = useState<Inbox | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api<Inbox>(`/api/purchases?offset=${offset}&limit=20`));
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [offset, setSession]);
  useEffect(() => {
    void load();
  }, [load]);
  useRefresh(load);
  return (
    <main className="workspace">
      <div className="page-heading">
        <div>
          <h1>Your purchases</h1>
          <p>Review pending baskets and return to your purchase history.</p>
        </div>
        <button onClick={load} disabled={busy}>
          {busy ? "Refreshing…" : "Refresh purchases"}
        </button>
      </div>
      <div className="inbox-caption">
        <span>All purchases</span>
        <span>Refreshes every 30 seconds while visible</span>
      </div>
      <ErrorMessage message={error} />
      {!data && !error ? (
        <p role="status" className="loading">
          Loading your purchases…
        </p>
      ) : data?.items.length === 0 ? (
        <section className="empty">
          <div className="empty-mark" aria-hidden="true">
            ✓
          </div>
          <h2>No purchases yet</h2>
          <p>
            Start a conversation to prepare your first basket.
            <br />
            Your decisions and demo receipts will appear here.
          </p>
        </section>
      ) : (
        <div className="purchase-list">
          {data?.items.map((p) => (
            <Link
              className="purchase-row"
              key={p.proposal_id}
              to={`/purchases/${p.proposal_id}`}
            >
              <div className="row-main">
                <Badge value={status(p)} />
                <h2>{p.request.request_id}</h2>
                <p>{p.snapshot.lines.map((l) => l.name).join(", ")}</p>
                <span className="muted">
                  {p.agent_id} • {p.request.destination}
                </span>
              </div>
              <div className="row-amount">
                <strong>{currency(p.snapshot.gross_total)}</strong>
                <span>Including tax & deposits</span>
                <span className="expiry">Expires {dateTime(p.expires_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
      <div className="pagination">
        <button
          disabled={offset === 0 || busy}
          onClick={() => setOffset(Math.max(0, offset - 20))}
        >
          Previous
        </button>
        <span>Page {Math.floor(offset / 20) + 1}</span>
        <button
          disabled={data?.next_offset == null || busy}
          onClick={() => setOffset(data?.next_offset ?? 0)}
        >
          Next
        </button>
      </div>
      <p className="muted small">
        Purchases are saved to your account. All times shown in Helsinki time.
      </p>
    </main>
  );
}

function DetailPage() {
  const { approvalId, proposalId } = useParams();
  const { session, setSession } = useContext(Auth);
  const currentDetail = `${proposalId ?? ""}/${approvalId ?? ""}`;
  const activeDetail = useRef(currentDetail);
  activeDetail.current = currentDetail;
  const [p, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    try {
      const result = await api<Proposal>(
        proposalId
          ? `/api/purchases/${proposalId}`
          : `/api/approvals/${approvalId}`,
      );
      if (activeDetail.current !== `${proposalId ?? ""}/${approvalId ?? ""}`) return;
      setProposal(result);
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    }
  }, [approvalId, proposalId, setSession]);
  useEffect(() => {
    setProposal(null);
    setMessage("");
    void load();
  }, [load]);
  const terminal = p
    ? [
        "accepted_mock",
        "expired",
        "rejected",
        "superseded",
        "policy_changed",
      ].includes(status(p))
    : false;
  useRefresh(load, !terminal);
  async function reject() {
    if (!p || !session || !p.approval_id) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setProposal(
        await api<Proposal>(`/api/approvals/${p.approval_id}/decision`, {
          method: "POST",
          headers: { "X-CSRF-Token": session.csrf_token },
          body: JSON.stringify({ decision: "reject", revision: p.revision }),
        }),
      );
      setMessage("Rejection recorded. This purchase cannot be committed.");
    } catch (e) {
      const msg = (e as Error).message;
      await load();
      setError(msg);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!p || !session) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const actorHash = await crypto.subtle.digest(
        "SHA-256", new TextEncoder().encode(session.username),
      );
      const actorKey = Array.from(new Uint8Array(actorHash)).slice(0, 12)
        .map((byte) => byte.toString(16).padStart(2, "0")).join("");
      const result = await api<Commit>(
        `/api/purchases/${p.proposal_id}/confirm`,
        {
          method: "POST",
          headers: { "X-CSRF-Token": session.csrf_token },
          body: JSON.stringify({
            proposal_id: p.proposal_id,
            revision: p.revision,
            idempotency_key: `customer-confirm-${p.proposal_id}-${p.revision}-${actorKey}`,
          }),
        },
      );
      await load();
      if (result.status === "revised") {
        setMessage(
          "Terms changed during verification. Review the new revision and confirm again.",
        );
      } else {
        setMessage("Confirmation saved. Your demo receipt is below.");
      }
    } catch (e) {
      const msg = (e as Error).message;
      await load();
      setError(msg);
    } finally {
      setBusy(false);
    }
  }
  const canConfirm =
    p &&
    p.revision === p.current_revision &&
    !terminal &&
    !["denied", "needs_resolution"].includes(p.policy_outcome) &&
    (p.policy_outcome === "ready_to_commit" ||
      p.can_decide ||
      p.approval_status === "approved");
  return (
    <main className="workspace">
      <Link className="back" to="/purchases">
        Back to purchases
      </Link>
      <ErrorMessage message={error} />
      {!p ? (
        <p role="status">
          {error ? "Purchase could not be loaded." : "Loading purchase…"}
        </p>
      ) : (
        <>
          <div className="page-heading">
            <div>
              <h1>{p.request.request_id}</h1>
              <p>
                Prepared by {p.agent_id} for {p.buyer_id}
              </p>
            </div>
            <Badge value={status(p)} />
          </div>
          <div className="mode-note">
            {p.snapshot.mode === "fixture"
              ? "Fixture prices and stock — invented for a repeatable demo."
              : "Supplier API evidence — rechecked before demo commitment."}{" "}
            Orders are accepted by the demo service only.
          </div>
          <div className="review-layout">
            <article className="purchase-sheet">
              <div className="delivery-grid">
                <div>
                  <span>Deliver to</span>
                  <strong>{p.request.destination}</strong>
                </div>
                <div>
                  <span>Delivery date</span>
                  <strong>{p.request.delivery_date}</strong>
                </div>
                <div>
                  <span>Valid until</span>
                  <strong>{dateTime(p.expires_at)}</strong>
                </div>
                <div>
                  <span>Proposal / policy</span>
                  <strong>
                    Revision {p.revision} / v{p.policy_version}
                  </strong>
                </div>
              </div>
              <h2>Purchase details</h2>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Requested</th>
                      <th>Proposed</th>
                      <th>Gross total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.snapshot.lines.map((l) => (
                      <tr key={l.product_id}>
                        <td>
                          <strong>{l.name}</strong>
                          <span className="muted">Product {l.product_id}</span>
                          {l.substitutes_for && (
                            <span className="exception-text">
                              Substitutes for {l.substitutes_for}
                            </span>
                          )}
                        </td>
                        <td>
                          {l.quantity.requested_amount}{" "}
                          {l.quantity.requested_unit}
                        </td>
                        <td>
                          {l.quantity.sales_quantity ?? "Unresolved"}{" "}
                          {l.quantity.sales_unit}
                          <span className="muted">
                            {l.quantity.proposed_amount}{" "}
                            {l.quantity.requested_unit}
                          </span>
                          {Number(l.quantity.excess) > 0 && (
                            <span className="exception-text">
                              +{l.quantity.excess} excess
                            </span>
                          )}
                        </td>
                        <td>
                          {currency(l.gross)}
                          <span className="muted">Tax {currency(l.tax)}</span>
                          {Number(l.deposits_gross) > 0 && (
                            <span className="muted">
                              Deposits {currency(l.deposits_gross)}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="totals">
                <div>
                  <span>Net total</span>
                  <span>{currency(p.snapshot.net_total)}</span>
                </div>
                <div>
                  <span>Tax</span>
                  <span>{currency(p.snapshot.tax_total)}</span>
                </div>
                <div>
                  <span>Deposits (included)</span>
                  <span>{currency(p.snapshot.deposits_gross)}</span>
                </div>
                <div>
                  <span>Demo delivery charges</span>
                  <span>{currency(p.snapshot.charges_gross)}</span>
                </div>
                <div className="grand-total">
                  <strong>Gross payable</strong>
                  <strong>{currency(p.snapshot.gross_total)}</strong>
                </div>
              </div>
              <section className="history">
                <h2>Decision history</h2>
                <ol>
                  {(p.history ?? []).map((event, i) => (
                    <li key={i}>
                      <span>{title(String(event.event))}</span>
                      <span className="muted">
                        {String(event.actor_id)} ·{" "}
                        {dateTime(String(event.created_at))}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
              <details>
                <summary>Evidence and calculations</summary>
                <p>
                  Observed {dateTime(p.snapshot.observed_at)}. Similarity and
                  product names do not prove dietary or quantity requirements.
                </p>
                <pre>
                  {JSON.stringify(
                    p.snapshot.lines.map((l) => ({
                      product_id: l.product_id,
                      quantity: l.quantity,
                      product: l.product_evidence,
                      commercial: l.commercial_evidence,
                    })),
                    null,
                    2,
                  )}
                </pre>
              </details>
            </article>
            <aside className="decision-panel">
              <h2>Review your basket</h2>
              <p className="decision-total">
                {currency(p.snapshot.gross_total)}
              </p>
              <h3>Purchasing checks</h3>
              <ul className="reasons">
                {p.reasons.map((r, i) => (
                  <li key={i}>
                    {r.message}
                    <span className="reason-code">{r.code}</span>
                  </li>
                ))}
              </ul>
              {p.request.budget_gross != null && (
                <p>
                  Mission budget: {currency(String(p.request.budget_gross))}
                </p>
              )}
              {message && (
                <p role="status" className="success">
                  {message}
                </p>
              )}
              {canConfirm ? (
                <>
                  <p className="action-note">
                    Your confirmation applies to revision {p.revision} only. We
                    recheck prices, availability and your authority before
                    recording a mock order. No supplier order or stock
                    reservation is made.
                  </p>
                  <button
                    className="primary full"
                    disabled={busy}
                    onClick={confirm}
                  >
                    {busy ? "Verifying purchase…" : "Confirm this purchase"}
                  </button>
                  {p.can_decide && status(p) === "pending" && (
                    <button
                      className="danger full"
                      disabled={busy}
                      onClick={reject}
                    >
                      Reject purchase
                    </button>
                  )}
                </>
              ) : (
                <div className="status-note">
                  <Badge value={status(p)} />
                  {status(p) === "superseded" && (
                    <p>
                      These terms were superseded.{" "}
                      <Link to={`/purchases/${p.proposal_id}`}>
                        View current revision {p.current_revision}
                      </Link>
                      {p.committed_revision != null &&
                        ` (revision ${p.committed_revision} was accepted).`}
                    </p>
                  )}
                  <p>
                    {p.order_id
                      ? "Accepted by demo order service. No real supplier order was placed."
                      : status(p) === "approved"
                        ? "A buyer decision is saved. Confirm this exact purchase to continue."
                        : status(p) === "pending"
                          ? "Your account does not have authority for this amount or exception."
                          : "This revision is closed for decisions."}
                  </p>
                  {p.order_id && (
                    <p className="order-reference">Order {p.order_id}</p>
                  )}
                </div>
              )}
              <button className="text-button" onClick={load}>
                Refresh status
              </button>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function Guard({ children }: { children: React.ReactNode }) {
  const { session } = useContext(Auth);
  const location = useLocation();
  return session ? (
    children
  ) : (
    <Navigate to="/login" replace state={{ from: location.pathname }} />
  );
}
function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Session>("/api/session")
      .then(setSession)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401))
          setError((e as Error).message);
      })
      .finally(() => setLoading(false));
  }, []);
  async function logout() {
    try {
      await api("/api/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": session?.csrf_token ?? "" },
      });
      setSession(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (loading)
    return (
      <main className="loading" role="status">
        Opening your purchasing workspace…
      </main>
    );
  return (
    <Auth.Provider value={{ session, setSession }}>
      <BrowserRouter>
        <header className="topbar">
          <Link to="/" className="brand" aria-label="Aimo purchasing home">
            aimo<span className="brand-dot">.</span>
          </Link>
          <nav className="product-nav" aria-label="Main navigation">
            <Link to="/">Plan a purchase</Link>
            <Link to="/purchases">Purchases</Link>
          </nav>
          {session && (
            <div className="account">
              <span>{session.buyer_id}</span>
              <button onClick={logout}>Sign out</button>
            </div>
          )}
        </header>
        <ErrorMessage message={error} />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/approvals"
            element={<Navigate to="/purchases" replace />}
          />
          <Route
            path="/purchases/:proposalId"
            element={
              <Guard>
                <DetailPage />
              </Guard>
            }
          />
          <Route
            path="/approvals/:approvalId"
            element={
              <Guard>
                <DetailPage />
              </Guard>
            }
          />
          <Route
            path="/"
            element={
              <Guard>
                <ChatPage />
              </Guard>
            }
          />
          <Route
            path="/conversations/:conversationId"
            element={
              <Guard>
                <ChatPage />
              </Guard>
            }
          />
          <Route
            path="/purchases"
            element={
              <Guard>
                <PurchasesPage />
              </Guard>
            }
          />
          <Route
            path="*"
            element={
              <main className="workspace">
                <h1>Page not found</h1>
                <Link to="/">Plan a purchase</Link>
              </main>
            }
          />
        </Routes>
      </BrowserRouter>
    </Auth.Provider>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
