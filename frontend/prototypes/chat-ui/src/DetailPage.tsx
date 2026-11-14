import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { Proposal } from "./types";
import { Badge, currency, dateTime, statusOf, title } from "./shared";
import { store } from "./store";
import { StickyConfirmPanel } from "./ConfirmPanels";

export function DetailPage() {
  const { approvalId, proposalId } = useParams();
  const [p, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setProposal(await store.getProposal(proposalId, approvalId));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [approvalId, proposalId]);
  useEffect(() => {
    setProposal(null);
    void load();
  }, [load]);

  return (
    <main className="workspace">
      <Link className="back" to="/purchases">
        Back to purchases
      </Link>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {!p ? (
        <p role="status">{error ? "Purchase could not be loaded." : "Loading purchase…"}</p>
      ) : (
        <>
          <div className="page-heading">
            <div>
              <h1>{p.request.request_id}</h1>
              <p>
                Prepared by {p.agent_id} for {p.buyer_id}
              </p>
            </div>
            <Badge value={statusOf(p)} />
          </div>
          <div className="mode-note">
            {p.snapshot.mode === "fixture"
              ? "Fixture prices and stock — invented for a repeatable demo."
              : "Supplier API evidence — rechecked before demo commitment."}{" "}
            Orders are accepted by the demo service only.
          </div>
          <div className="review-layout">
            <article className="purchase-sheet">
              <div className="delivery-grid">
                <div>
                  <span>Deliver to</span>
                  <strong>{p.request.destination}</strong>
                </div>
                <div>
                  <span>Delivery date</span>
                  <strong>{p.request.delivery_date}</strong>
                </div>
                <div>
                  <span>Valid until</span>
                  <strong>{dateTime(p.expires_at)}</strong>
                </div>
                <div>
                  <span>Proposal / policy</span>
                  <strong>
                    Revision {p.revision} / v{p.policy_version}
                  </strong>
                </div>
              </div>
              <h2>Purchase details</h2>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Requested</th>
                      <th>Proposed</th>
                      <th>Gross total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.snapshot.lines.map((l) => (
                      <tr key={l.product_id}>
                        <td>
                          <strong>{l.name}</strong>
                          <span className="muted">Product {l.product_id}</span>
                          {l.substitutes_for && (
                            <span className="exception-text">Substitutes for {l.substitutes_for}</span>
                          )}
                        </td>
                        <td>
                          {l.quantity.requested_amount} {l.quantity.requested_unit}
                        </td>
                        <td>
                          {l.quantity.sales_quantity ?? "Unresolved"} {l.quantity.sales_unit}
                          <span className="muted">
                            {l.quantity.proposed_amount} {l.quantity.requested_unit}
                          </span>
                          {Number(l.quantity.excess) > 0 && (
                            <span className="exception-text">+{l.quantity.excess} excess</span>
                          )}
                        </td>
                        <td>
                          {currency(l.gross)}
                          <span className="muted">Tax {currency(l.tax)}</span>
                          {Number(l.deposits_gross) > 0 && (
                            <span className="muted">Deposits {currency(l.deposits_gross)}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="totals">
                <div>
                  <span>Net total</span>
                  <span>{currency(p.snapshot.net_total)}</span>
                </div>
                <div>
                  <span>Tax</span>
                  <span>{currency(p.snapshot.tax_total)}</span>
                </div>
                <div>
                  <span>Deposits (included)</span>
                  <span>{currency(p.snapshot.deposits_gross)}</span>
                </div>
                <div>
                  <span>Demo delivery charges</span>
                  <span>{currency(p.snapshot.charges_gross)}</span>
                </div>
                <div className="grand-total">
                  <strong>Gross payable</strong>
                  <strong>{currency(p.snapshot.gross_total)}</strong>
                </div>
              </div>
              <section className="history">
                <h2>Decision history</h2>
                <ol>
                  {(p.history ?? []).map((event, i) => (
                    <li key={i}>
                      <span>{title(event.event)}</span>
                      <span className="muted">
                        {event.actor_id} · {dateTime(event.created_at)}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
              <details>
                <summary>Evidence and calculations</summary>
                <p>
                  Observed {dateTime(p.snapshot.observed_at)}. Similarity and product names do not prove dietary
                  or quantity requirements.
                </p>
                <pre>
                  {JSON.stringify(
                    p.snapshot.lines.map((l) => ({
                      product_id: l.product_id,
                      quantity: l.quantity,
                      product: l.product_evidence,
                      commercial: l.commercial_evidence,
                    })),
                    null,
                    2,
                  )}
                </pre>
              </details>
            </article>
            <StickyConfirmPanel p={p} onUpdate={setProposal} />
          </div>
        </>
      )}
    </main>
  );
}
