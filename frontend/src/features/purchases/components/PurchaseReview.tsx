import { Link } from "react-router-dom";
import { Badge } from "../../../shared/components/Badge";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { getPurchaseStatus } from "../model/purchaseStatus";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { PurchaseSheet } from "./PurchaseSheet";
import { OverviewPanel } from "./OverviewPanel";
export function PurchaseReview({
  flow,
  notice,
}: {
  flow: ReturnType<typeof usePurchaseDetail>;
  notice?: string;
}) {
  const { p, error, errorDebug } = flow;
  return (
    <main className="workspace mx-auto w-full max-w-[1320px] px-4 py-7 md:px-8 md:py-10">
      <Link
        className="mb-6 inline-flex font-label text-label-md font-bold text-wholesale-teal"
        to="/purchases"
      >
        Back to purchases
      </Link>
      {notice && (
        <p
          role="note"
          className="rounded-lg bg-secondary-container p-4 text-body-sm text-primary"
        >
          {notice}
        </p>
      )}
      <ErrorMessage message={!p ? error : ""} debug={errorDebug} />
      {!p ? (
        <p role="status">
          {error ? "Purchase could not be loaded." : "Loading purchase…"}
        </p>
      ) : (
        <>
          <div className="page-heading mb-8 flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row sm:items-center [&_h1]:wrap-anywhere [&_h1]:text-headline-lg-mobile md:[&_h1]:text-headline-lg [&_p]:m-0 [&_p]:text-secondary">
            <div>
              <h1>{p.request.request_id}</h1>
              <p>
                Prepared by {p.agent_id} for {p.buyer_id}
              </p>
            </div>
            <Badge value={getPurchaseStatus(p)} />
          </div>
          <div className="mode-note mb-6 rounded-lg border border-border-subtle border-l-4 border-l-wholesale-teal bg-secondary-container/40 px-4 py-3 text-body-sm text-primary">
            {p.snapshot.mode === "fixture"
              ? "Catalog prices and stock for this basket."
              : "Supplier API evidence — rechecked before commitment."}{" "}
            Orders are recorded after your confirmation.
          </div>
          <div className="review-layout grid min-w-0 grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_352px]">
            <PurchaseSheet p={p} />
            <OverviewPanel flow={flow} drawer={false} showEvidence={false} />
          </div>
        </>
      )}
    </main>
  );
}
