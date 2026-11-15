import { Link } from "react-router-dom";
import type { Proposal } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge";
import { InertButton } from "../../../shared/components/DesignPrimitives";
import { currency } from "../../../shared/lib/format";
import { CART_COPY } from "../model/cartCopy";
import { getPurchaseStatus } from "../model/purchaseStatus";
type Props = {
  p: Proposal;
  busy: boolean;
  /** Greys the confirm button without changing its label (the assistant is working on the cart). */
  disabled?: boolean;
  message: string;
  canConfirm: boolean;
  confirm: () => Promise<void>;
  reject: () => Promise<void>;
  load: () => Promise<void>;
};
export function PurchaseDecisionPanel({
  p,
  busy,
  disabled = false,
  message,
  canConfirm,
  confirm,
  reject,
  load,
}: Props) {
  return (
    <section className="decision-panel [&_h3]:font-label [&_h3]:text-label-md [&_h3]:text-secondary">
      <h3>Purchasing checks</h3>
      {["denied", "needs_resolution"].includes(p.policy_outcome) && (
        <p
          role="alert"
          className="mb-3 rounded-lg bg-error-container p-3 text-body-sm text-on-error-container"
        >
          This purchase cannot be approved. Resolve the purchasing checks below.
        </p>
      )}
      <ul className="m-0 mb-5 list-none space-y-3 p-0 text-body-sm">
        {p.reasons.map((r, i) => (
          <li key={i}>
            {r.message}
            <span className="mt-1 block font-label text-label-sm text-secondary wrap-anywhere">
              {r.code}
            </span>
          </li>
        ))}
      </ul>
      {p.request.budget_gross != null && (
        <p>Mission budget: {currency(String(p.request.budget_gross))}</p>
      )}
      {message && (
        <p
          role="status"
          className="my-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-body-sm text-green-900"
        >
          {message}
        </p>
      )}
      {canConfirm ? (
        <>
          <p className="my-4 border-t border-border-subtle pt-4 text-body-sm text-secondary">
            Your confirmation applies to revision {p.revision} only. We recheck
            prices, availability and your authority before recording a mock
            order. No supplier order or stock reservation is made.
          </p>
          <button
            className="primary full mt-3 block w-full rounded border border-status-fresh-green bg-status-fresh-green px-4 py-3 font-label text-label-lg font-bold text-deep-ocean-navy hover:enabled:bg-tertiary-fixed"
            disabled={busy || disabled}
            onClick={confirm}
          >
            {busy ? "Verifying purchase…" : CART_COPY.button}
          </button>
          <InertButton
            label="Save as Draft"
            className="mt-2 w-full rounded-lg bg-surface-container px-space-sm py-2.5 font-label text-label-sm font-bold"
          >
            Save as Draft
          </InertButton>
          {p.can_decide && getPurchaseStatus(p) === "pending" && (
            <button
              className="danger full mt-3 block w-full rounded border border-error bg-transparent px-4 py-3 font-label text-label-md font-bold text-error hover:enabled:bg-error-container"
              disabled={busy}
              onClick={reject}
            >
              Reject
            </button>
          )}
        </>
      ) : (
        <div className="status-note border-t border-border-subtle pt-4 [&_p]:mt-4 [&_p]:text-body-sm">
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
          {p.order_id && (
            <p className="order-reference font-label font-bold text-primary wrap-anywhere">
              Order {p.order_id}
            </p>
          )}
        </div>
      )}
      <button
        className="mt-4 border-0 bg-transparent px-0 font-label text-label-md font-bold text-wholesale-teal hover:enabled:bg-transparent hover:enabled:underline"
        onClick={load}
      >
        Refresh status
      </button>
    </section>
  );
}
