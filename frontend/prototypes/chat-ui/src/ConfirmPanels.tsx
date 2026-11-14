import { useState } from "react";
import type { Proposal } from "./types";
import { Badge, canConfirm, currency, statusOf } from "./shared";
import { useConfirmFlow } from "./confirmFlow";
import { store } from "./store";
import { VLink } from "./variant";

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

function ActionNote() {
  return (
    <p className="action-note">
      Your confirmation applies to this revision only. We recheck prices, availability and your
      authority before recording a mock order. No supplier order or stock reservation is made.
    </p>
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

type PanelProps = { p: Proposal; onUpdate: (p: Proposal) => void; threadHref?: string };

// Variant A (#26): confirmation lives on a sticky bar pinned to the bottom
// of the viewport while the buyer scrolls the basket — the closest cousin
// of the real PR #13 decision panel, made literally a sticky bar.
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

// Variant B (#27): the basket page shows a plain summary; a button opens a
// modal that restates the exact terms before the buyer can confirm.
export function ModalConfirmPanel({ p, onUpdate }: PanelProps) {
  const flow = useConfirmFlow(onUpdate);
  const [open, setOpen] = useState(false);
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
    <aside className="decision-panel">
      <h2>Review your basket</h2>
      <p className="decision-total">{currency(p.snapshot.gross_total)}</p>
      <ActionNote />
      {flow.message && <p role="status" className="success">{flow.message}</p>}
      {flow.error && <ErrorInline message={flow.error} />}
      <button className="primary full" onClick={() => setOpen(true)}>
        Review &amp; confirm…
      </button>
      {open && (
        <div className="modal-overlay" role="presentation" onClick={() => !flow.busy && setOpen(false)}>
          <div
            className="modal-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Confirm this purchase"
            onClick={(e) => e.stopPropagation()}
          >
            <h2>Confirm these exact terms</h2>
            <dl className="modal-terms">
              <div>
                <dt>Request</dt>
                <dd>{p.request.request_id}</dd>
              </div>
              <div>
                <dt>Deliver to</dt>
                <dd>{p.request.destination}</dd>
              </div>
              <div>
                <dt>Delivery date</dt>
                <dd>{p.request.delivery_date}</dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd>
                  {p.revision} / policy v{p.policy_version}
                </dd>
              </div>
              <div>
                <dt>Total payable</dt>
                <dd className="modal-total">{currency(p.snapshot.gross_total)}</dd>
              </div>
            </dl>
            <ul className="reasons">
              {p.reasons.map((r, i) => (
                <li key={i}>
                  {r.message}
                  <span className="reason-code">{r.code}</span>
                </li>
              ))}
            </ul>
            {flow.error && <ErrorInline message={flow.error} />}
            <div className="modal-actions">
              <ConfirmRejectButtons
                p={p}
                busy={flow.busy}
                onConfirm={() => flow.confirm(p)}
                onReject={() => flow.reject(p)}
              />
              <button className="text-button" disabled={flow.busy} onClick={() => setOpen(false)}>
                Cancel, keep reviewing
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}

// Variant C (#28): the primary confirm/reject lives on the proposal card
// inside the chat thread (see InlineThreadCard). Basket detail keeps the
// same action available for full-surface parity, labelled as the secondary
// path back to the thread.
export function InlineVariantPanel({ p, onUpdate, threadHref }: PanelProps) {
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
    <aside className="decision-panel">
      <h2>Review your basket</h2>
      <p className="decision-total">{currency(p.snapshot.gross_total)}</p>
      <p className="inline-variant-note">
        In this variant, confirmation is primarily on the proposal card inside the chat thread.
        {threadHref && <> <VLink to={threadHref}>Back to the conversation</VLink>.</>}
      </p>
      <ActionNote />
      {flow.message && <p role="status" className="success">{flow.message}</p>}
      {flow.error && <ErrorInline message={flow.error} />}
      <ConfirmRejectButtons p={p} busy={flow.busy} onConfirm={() => flow.confirm(p)} onReject={() => flow.reject(p)} />
    </aside>
  );
}

export function ConfirmPanel(
  props: PanelProps & { variant: "sticky" | "modal" | "inline" },
) {
  if (props.variant === "modal") return <ModalConfirmPanel {...props} />;
  if (props.variant === "inline") return <InlineVariantPanel {...props} />;
  return <StickyConfirmPanel {...props} />;
}
