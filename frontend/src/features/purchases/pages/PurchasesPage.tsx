import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { usePurchases } from "../hooks/usePurchases";
import { PurchaseList } from "../components/PurchaseList";
export function PurchasesPage() {
  const { data, offset, setOffset, error, busy, load } = usePurchases();
  return (
    <main className="workspace mx-auto w-full max-w-[1320px] px-4 py-7 md:px-8 md:py-10">
      <div className="page-heading mb-8 flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row sm:items-center [&_h1]:wrap-anywhere [&_h1]:text-headline-lg-mobile md:[&_h1]:text-headline-lg [&_p]:m-0 [&_p]:text-secondary">
        <div>
          <h1>Your purchases</h1>
          <p>Review pending baskets and return to your purchase history.</p>
        </div>
        <button onClick={load} disabled={busy}>
          {busy ? "Refreshing…" : "Refresh purchases"}
        </button>
      </div>
      <div className="mb-4 flex flex-wrap justify-between gap-2 font-label text-label-md text-secondary [&>span:first-child]:font-bold [&>span:first-child]:text-primary">
        <span>All purchases</span>
        <span>Refreshes every 30 seconds while visible</span>
      </div>
      <ErrorMessage message={error} />
      {!data && !error ? (
        <p
          role="status"
          className="loading px-4 py-12 text-center text-secondary"
        >
          Loading your purchases…
        </p>
      ) : data?.items.length === 0 ? (
        <section className="rounded-xl border border-border-subtle bg-surface-pure px-5 py-16 text-center [&_p]:mx-auto [&_p]:text-secondary">
          <div className="mb-4 text-3xl text-wholesale-teal" aria-hidden="true">
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
      <div className="my-6 flex flex-wrap items-center justify-end gap-3 font-label text-label-md">
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
      <p className="text-body-sm text-secondary">
        Purchases are saved to your account. All times shown in Helsinki time.
      </p>
    </main>
  );
}
