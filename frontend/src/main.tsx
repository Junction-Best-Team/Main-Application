import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
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
  useParams,
} from "react-router-dom";
import type { components } from "./api-types";
import "./style.css";

type Session = components["schemas"]["SessionResponse"];
type Proposal = components["schemas"]["ProposalResponse"];
type Inbox = components["schemas"]["InboxResponse"];
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
          : "Unable to load the purchase. Try again."),
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
    typeof next === "string" && /^\/(approvals|purchases)(\/|$)/.test(next)
      ? next
      : "/approvals";
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
          A clear decision.
          <br />A considered purchase.
        </h1>
        <p>
          Review purchases prepared by your agent. You decide on permitted
          exceptions before the agent can place a demo order.
        </p>
        <div className="welcome-note">
          Your inbox is available independently of your agent or chat.
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

function InboxPage() {
  const { setSession } = useContext(Auth);
  const [data, setData] = useState<Inbox | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api<Inbox>(`/api/approvals?offset=${offset}&limit=20`));
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
          <h1>Purchase approvals</h1>
          <p>Purchases waiting for a buyer decision.</p>
        </div>
        <button onClick={load} disabled={busy}>
          {busy ? "Refreshing…" : "Refresh inbox"}
        </button>
      </div>
      <div className="inbox-caption">
        <span>Pending requests</span>
        <span>Refreshes every 30 seconds while visible</span>
      </div>
      <ErrorMessage message={error} />
      {!data && !error ? (
        <p role="status" className="loading">
          Loading your inbox…
        </p>
      ) : data?.items.length === 0 ? (
        <section className="empty">
          <div className="empty-mark" aria-hidden="true">
            ✓
          </div>
          <h2>No pending decisions</h2>
          <p>
            Requests appear here when your agent needs an approval.
            <br />
            You can return to this page at any time.
          </p>
        </section>
      ) : (
        <div className="purchase-list">
          {data?.items.map((p) => (
            <Link
              className="purchase-row"
              key={p.proposal_id}
              to={`/approvals/${p.approval_id}`}
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
        This inbox does not send email or push notifications. All times shown in
        Helsinki time.
      </p>
    </main>
  );
}

function DetailPage() {
  const { approvalId, proposalId } = useParams();
  const { session, setSession } = useContext(Auth);
  const [p, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    try {
      setProposal(
        await api<Proposal>(
          proposalId
            ? `/api/purchases/${proposalId}`
            : `/api/approvals/${approvalId}`,
        ),
      );
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    }
  }, [approvalId, proposalId, setSession]);
  useEffect(() => {
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
  async function decide(decision: "approve" | "reject") {
    if (!p || !session) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<Proposal>(
        `/api/approvals/${p.approval_id}/decision`,
        {
          method: "POST",
          headers: { "X-CSRF-Token": session.csrf_token },
          body: JSON.stringify({ decision, revision: p.revision }),
        },
      );
      setProposal(result);
      setMessage(
        decision === "approve"
          ? "Approval recorded. Your agent can now recheck terms and commit the purchase."
          : "Rejection recorded. This purchase cannot be committed.",
      );
    } catch (e) {
      const msg = (e as Error).message;
      await load();
      setError(msg);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="workspace">
      <Link className="back" to="/approvals">
        Back to inbox
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
              <h2>Buyer decision</h2>
              <p className="decision-total">
                {currency(p.snapshot.gross_total)}
              </p>
              <h3>Why your decision is needed</h3>
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
              {p.can_decide && status(p) === "pending" ? (
                <>
                  <p className="action-note">
                    Approval applies to this revision only. It does not place an
                    order, reserve stock or raise your standing limit.
                  </p>
                  <button
                    className="primary full"
                    disabled={busy}
                    onClick={() => decide("approve")}
                  >
                    {busy ? "Recording decision…" : "Approve this purchase"}
                  </button>
                  <button
                    className="danger full"
                    disabled={busy}
                    onClick={() => decide("reject")}
                  >
                    Reject purchase
                  </button>
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
                        ? "Waiting for the agent to resume and commit. Terms and authority will be checked again."
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
        Opening buyer inbox…
      </main>
    );
  return (
    <Auth.Provider value={{ session, setSession }}>
      <BrowserRouter>
        <header className="topbar">
          <Link
            to="/approvals"
            className="brand"
            aria-label="Aimo purchase approvals"
          >
            aimo<span className="brand-dot">.</span>
          </Link>
          <span className="topbar-title">Buyer approvals</span>
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
            element={
              <Guard>
                <InboxPage />
              </Guard>
            }
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
          <Route path="/" element={<Navigate to="/approvals" replace />} />
          <Route
            path="*"
            element={
              <main className="workspace">
                <h1>Page not found</h1>
                <Link to="/approvals">Open purchase approvals</Link>
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
