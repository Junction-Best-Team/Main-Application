import { Link, useParams } from "react-router-dom";
import { Badge } from "../../../shared/components/Badge";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { getPurchaseStatus } from "../model/purchaseStatus";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { PurchaseSheet } from "../components/PurchaseSheet";
import { PurchaseDecisionPanel } from "../components/PurchaseDecisionPanel";
export function PurchaseDetailPage() {
  const { approvalId, proposalId } = useParams();
  const { p, error, busy, message, load, confirm, reject, canConfirm } =
    usePurchaseDetail({ approvalId, proposalId });
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
            <Badge value={getPurchaseStatus(p)} />
          </div>
          <div className="mode-note">
            {p.snapshot.mode === "fixture"
              ? "Fixture prices and stock — invented for a repeatable demo."
              : "Supplier API evidence — rechecked before demo commitment."}{" "}
            Orders are accepted by the demo service only.
          </div>
          <div className="review-layout">
            <PurchaseSheet p={p} />
            <PurchaseDecisionPanel
              p={p}
              busy={busy}
              message={message}
              canConfirm={canConfirm}
              confirm={confirm}
              reject={reject}
              load={load}
            />
          </div>
        </>
      )}
    </main>
  );
}
