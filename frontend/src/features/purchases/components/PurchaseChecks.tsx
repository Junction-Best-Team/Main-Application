import { useState } from "react";
import { Link } from "react-router-dom";
import type { Proposal } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { getPurchaseStatus } from "../model/purchaseStatus";
import { PurchaseSheet } from "./PurchaseSheet";

/**
 * The Checks tab: the purchasing checks with their codes, what the confirmation covers, the mock
 * labelling, and More (the full details of the basket). A blocker is also on the pinned footer;
 * this is where its full sentence and code are.
 */
export function PurchaseChecks({
  p,
  canConfirm,
  showEvidence,
  load,
}: {
  p: Proposal;
  canConfirm: boolean;
  showEvidence: boolean;
  load: () => Promise<void>;
}) {
  const [more, setMore] = useState(false);
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
      <p className="m-0 rounded bg-secondary-container/40 p-2 text-body-sm text-primary">
        {p.snapshot.mode === "fixture"
          ? "Fixture prices and stock — invented for a repeatable demo."
          : "Supplier API evidence — rechecked before demo commitment."}{" "}
        Orders are accepted by the demo service only.
      </p>
      {canConfirm && (
        <p className="m-0 text-body-sm text-secondary">
          Your confirmation applies to revision {p.revision} only. We recheck
          prices, availability and your authority before recording a mock order.
          No supplier order or stock reservation is made.
        </p>
      )}
      <p className="m-0 font-label text-label-sm text-secondary">
        Revision {p.revision} / v{p.policy_version}
      </p>
      {showEvidence && (
        <>
          <button
            type="button"
            aria-expanded={more}
            onClick={() => setMore((open) => !open)}
            className="cursor-pointer self-start border-0 bg-transparent px-0 font-label text-label-md font-bold text-wholesale-teal hover:underline"
          >
            More
          </button>
          {more && <PurchaseSheet p={p} />}
        </>
      )}
      <button
        type="button"
        onClick={load}
        className="cursor-pointer self-start border-0 bg-transparent px-0 font-label text-label-md font-bold text-wholesale-teal hover:underline"
      >
        Refresh status
      </button>
    </section>
  );
}
