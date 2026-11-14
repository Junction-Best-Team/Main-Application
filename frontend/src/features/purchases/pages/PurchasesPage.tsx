import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { usePurchases } from "../hooks/usePurchases";
import { PurchaseList } from "../components/PurchaseList";
export function PurchasesPage() {
  const { data, offset, setOffset, error, busy, load } = usePurchases();
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
        <PurchaseList items={data?.items ?? []} />
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
