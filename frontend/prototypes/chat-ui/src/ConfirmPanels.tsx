import type { Proposal } from "./types";
import { Badge, canConfirm, currency, statusOf } from "./shared";
import { useConfirmFlow } from "./confirmFlow";
import { store } from "./store";

function StatusNote({ p, onUpdate }: { p: Proposal; onUpdate: (p: Proposal) => void }) {
  const s = statusOf(p);
  async function viewCurrentRevision() {
    // Fixture-only stand-in for "the backend's next GET already returns the
    // latest revision" — see README.md known simplifications.
    store.advanceSuperseded(p.proposal_id);
    onUpdate(await store.getProposal(p.proposal_id));
  }
  return (
    <div className="status-note">
      <Badge value={s} />
      {s === "superseded" && (
        <p>
          These terms were superseded.{" "}
          <button className="text-button inline" onClick={() => void viewCurrentRevision()}>
            View current revision {p.current_revision}
          </button>
          {p.committed_revision != null && ` (revision ${p.committed_revision} was accepted).`}
        </p>
      )}
      <p>
        {p.order_id
          ? "Accepted by demo order service. No real supplier order was placed."
          : s === "approved"
            ? "A buyer decision is saved. Confirm this exact purchase to continue."
            : s === "pending"
              ? "Your account does not have authority for this amount or exception."
              : "This revision is closed for decisions."}
      </p>
      {p.order_id && <p className="order-reference">Order {p.order_id}</p>}
    </div>
  );
}

function ConfirmRejectButtons({
  p,
  busy,
  onConfirm,
  onReject,
}: {
  p: Proposal;
  busy: boolean;
  onConfirm: () => void;
  onReject: () => void;
}) {
  return (
    <>
      <button className="primary full" disabled={busy} onClick={onConfirm}>
        {busy ? "Verifying purchase…" : "Confirm this purchase"}
      </button>
      {p.can_decide && statusOf(p) === "pending" && (
        <button className="danger full" disabled={busy} onClick={onReject}>
          Reject purchase
        </button>
      )}
    </>
  );
}

type PanelProps = { p: Proposal; onUpdate: (p: Proposal) => void };

// The single confirmation path: a bar pinned to the bottom of the viewport
// while the buyer scrolls the basket, restating the total and Confirm/Reject.
export function StickyConfirmPanel({ p, onUpdate }: PanelProps) {
  const flow = useConfirmFlow(onUpdate);
  if (!canConfirm(p)) {
    return (
      <aside className="decision-panel">
        <h2>Review your basket</h2>
        <p className="decision-total">{currency(p.snapshot.gross_total)}</p>
        {flow.message && <p role="status" className="success">{flow.message}</p>}
        <StatusNote p={p} onUpdate={onUpdate} />
      </aside>
    );
  }
  return (
    <>
      <aside className="decision-panel sticky-bar-placeholder">
        <h2>Review your basket</h2>
        <p className="decision-total">{currency(p.snapshot.gross_total)}</p>
        <p className="muted small">Confirm from the sticky bar below — it stays visible while you scroll.</p>
      </aside>
      <div className="sticky-confirm-bar" role="region" aria-label="Confirm this purchase">
        <div className="sticky-confirm-bar-total">
          <span>Total payable</span>
          <strong>{currency(p.snapshot.gross_total)}</strong>
        </div>
        {flow.error && <ErrorInline message={flow.error} />}
        {flow.message && <p role="status" className="success">{flow.message}</p>}
        <div className="sticky-confirm-bar-actions">
          <ConfirmRejectButtons p={p} busy={flow.busy} onConfirm={() => flow.confirm(p)} onReject={() => flow.reject(p)} />
        </div>
      </div>
    </>
  );
}

function ErrorInline({ message }: { message: string }) {
  return (
    <div className="error" role="alert">
      {message}
    </div>
  );
}
