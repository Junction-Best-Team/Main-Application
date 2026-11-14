import { useEffect, useState } from "react";
import type { Proposal, Variant } from "./types";
import { Badge, canConfirm, currency, statusOf } from "./shared";
import { useConfirmFlow } from "./confirmFlow";
import { store } from "./store";
import { VLink } from "./variant";

// The one place the three variants diverge inside the chat transcript:
// sticky/modal keep the original plain link to basket detail; inline (#28)
// embeds confirm/reject directly on the proposal card in the thread.
export function ProposalCard({ proposalId, variant }: { proposalId: string; variant: Variant }) {
  if (variant !== "inline") {
    return (
      <VLink className="basket-link" to={`/purchases/${proposalId}`}>
        Review basket and purchasing checks
      </VLink>
    );
  }
  return <InlineConfirmCard proposalId={proposalId} />;
}

function InlineConfirmCard({ proposalId }: { proposalId: string }) {
  const [p, setP] = useState<Proposal | null>(null);
  const [loadError, setLoadError] = useState("");
  const flow = useConfirmFlow(setP);

  useEffect(() => {
    let active = true;
    store
      .getProposal(proposalId)
      .then((result) => active && setP(result))
      .catch((e) => active && setLoadError((e as Error).message));
    return () => {
      active = false;
    };
  }, [proposalId]);

  if (loadError) return <div className="error" role="alert">{loadError}</div>;
  if (!p) return <p className="muted small">Loading basket…</p>;

  return (
    <section className="inline-proposal-card" aria-label="Proposal — confirm inline">
      <div className="inline-proposal-head">
        <strong>{currency(p.snapshot.gross_total)}</strong>
        <Badge value={statusOf(p)} />
      </div>
      <p className="muted small">
        {p.snapshot.lines.length} catalog line{p.snapshot.lines.length === 1 ? "" : "s"} · Revision{" "}
        {p.revision} · Valid until {p.request.delivery_date}
      </p>
      {flow.message && (
        <p role="status" className="success">
          {flow.message}
        </p>
      )}
      {flow.error && (
        <div className="error" role="alert">
          {flow.error}
        </div>
      )}
      {canConfirm(p) ? (
        <>
          <p className="action-note">
            Confirming applies to revision {p.revision} only. Messages never authorize this — this
            button is the authenticated confirmation.
          </p>
          <div className="inline-proposal-actions">
            <button className="primary" disabled={flow.busy} onClick={() => flow.confirm(p)}>
              {flow.busy ? "Verifying purchase…" : "Confirm this purchase"}
            </button>
            {p.can_decide && statusOf(p) === "pending" && (
              <button className="danger" disabled={flow.busy} onClick={() => flow.reject(p)}>
                Reject purchase
              </button>
            )}
          </div>
        </>
      ) : (
        <p className="muted small">
          {p.order_id
            ? `Accepted by demo order service. Order ${p.order_id}.`
            : "This basket is no longer open for a decision here."}
        </p>
      )}
      <VLink className="basket-link secondary" to={`/purchases/${p.proposal_id}`}>
        Open full basket detail
      </VLink>
    </section>
  );
}
