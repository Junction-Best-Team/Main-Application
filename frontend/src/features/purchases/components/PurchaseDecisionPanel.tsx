import { Link } from "react-router-dom";
import type { Proposal } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge";
import { currency } from "../../../shared/lib/format";
import { getPurchaseStatus } from "../model/purchaseStatus";
type Props = {
  p: Proposal;
  busy: boolean;
  message: string;
  canConfirm: boolean;
  confirm: () => Promise<void>;
  reject: () => Promise<void>;
  load: () => Promise<void>;
};
export function PurchaseDecisionPanel({
  p,
  busy,
  message,
  canConfirm,
  confirm,
  reject,
  load,
}: Props) {
  return (
    <aside className="decision-panel">
      <h2>Review your basket</h2>
      <p className="decision-total">{currency(p.snapshot.gross_total)}</p>
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
        <p>Mission budget: {currency(String(p.request.budget_gross))}</p>
      )}
      {message && (
        <p role="status" className="success">
          {message}
        </p>
      )}
      {canConfirm ? (
        <>
          <p className="action-note">
            Your confirmation applies to revision {p.revision} only. We recheck
            prices, availability and your authority before recording a mock
            order. No supplier order or stock reservation is made.
          </p>
          <button className="primary full" disabled={busy} onClick={confirm}>
            {busy ? "Verifying purchase…" : "Confirm this purchase"}
          </button>
          {p.can_decide && getPurchaseStatus(p) === "pending" && (
            <button className="danger full" disabled={busy} onClick={reject}>
              Reject purchase
            </button>
          )}
        </>
      ) : (
        <div className="status-note">
          <Badge value={getPurchaseStatus(p)} />
          {getPurchaseStatus(p) === "superseded" && (
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
              : getPurchaseStatus(p) === "approved"
                ? "A buyer decision is saved. Confirm this exact purchase to continue."
                : getPurchaseStatus(p) === "pending"
                  ? "Your account does not have authority for this amount or exception."
                  : "This revision is closed for decisions."}
          </p>
          {p.order_id && <p className="order-reference">Order {p.order_id}</p>}
        </div>
      )}
      <button className="text-button" onClick={load}>
        Refresh status
      </button>
    </aside>
  );
}
