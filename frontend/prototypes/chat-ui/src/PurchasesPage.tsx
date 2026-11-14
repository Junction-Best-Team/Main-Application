import { useCallback, useEffect, useState } from "react";
import type { Inbox } from "./types";
import { Badge, ErrorMessage, currency, dateTime, statusOf } from "./shared";
import { store } from "./store";
import { VLink } from "./variant";

export function PurchasesPage() {
  const [data, setData] = useState<Inbox | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await store.listPurchases());
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

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
        <span>Prototype: fake JSON, no live refresh</span>
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
            <VLink className="purchase-row" key={p.proposal_id} to={`/purchases/${p.proposal_id}`}>
              <div className="row-main">
                <Badge value={statusOf(p)} />
                <h2>{p.request.request_id}</h2>
                <p>{p.snapshot.lines.map((l) => l.name).join(", ")}</p>
                <span className="muted">
                  {p.agent_id} • {p.request.destination}
                </span>
              </div>
              <div className="row-amount">
                <strong>{currency(p.snapshot.gross_total)}</strong>
                <span>Including tax &amp; deposits</span>
                <span className="expiry">Expires {dateTime(p.expires_at)}</span>
              </div>
            </VLink>
          ))}
        </div>
      )}
      <div className="pagination">
        <button disabled>Previous</button>
        <span>Page 1</span>
        <button disabled>Next</button>
      </div>
      <p className="muted small">Purchases are saved to your account. All times shown in Helsinki time.</p>
    </main>
  );
}
