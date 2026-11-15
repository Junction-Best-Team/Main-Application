import { Link } from "react-router-dom";
import type { Proposal } from "../../../shared/api/types";
import { currency, title } from "../../../shared/lib/format";
import { getPurchaseStatus } from "../model/purchaseStatus";

/**
 * The Checks tab: only what blocks or conditions the order: the purchasing checks with their codes and the
 * approval status. A blocker is also on the pinned footer; this is where its full sentence and code are.
 */
export function PurchaseChecks({ p }: { p: Proposal }) {
  const status = getPurchaseStatus(p);
  return (
    <section className="decision-panel flex flex-col gap-space-sm [&_h3]:font-label [&_h3]:text-label-md [&_h3]:text-secondary">
      <h3 className="m-0">Purchasing checks</h3>
      {["denied", "needs_resolution"].includes(p.policy_outcome) && (
        <p
          role="alert"
          className="m-0 rounded-lg bg-error-container p-3 text-body-sm text-on-error-container"
        >
          This purchase cannot be approved. Resolve the purchasing checks below.
        </p>
      )}
      <ul className="m-0 list-none space-y-3 p-0 text-body-sm">
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
        <p className="m-0">
          Mission budget: {currency(String(p.request.budget_gross))}
        </p>
      )}
      <p
        data-testid="card-approval"
        className="m-0 text-body-sm text-secondary"
      >
        Approval: {title(p.approval_status).toLowerCase()}
      </p>
      {status === "superseded" && (
        <p className="m-0 text-body-sm">
          These terms were superseded.{" "}
          <Link to={`/purchases/${p.proposal_id}`}>
            View current revision {p.current_revision}
          </Link>
          {p.committed_revision != null &&
            ` (revision ${p.committed_revision} was accepted).`}
        </p>
      )}
    </section>
  );
}
