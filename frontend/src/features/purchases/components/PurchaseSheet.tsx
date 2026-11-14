import type { Proposal } from "../../../shared/api/types";
import { currency, dateTime, title } from "../../../shared/lib/format";
export function PurchaseSheet({ p }: { p: Proposal }) {
  return (
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
      <p className="mode-note">
        {p.recipe_basis === "saved_recipe"
          ? "Recipe-backed basket — includes every ingredient from the saved recipe plan."
          : "Free-form basket — recipe completeness and ingredient conversions are not checked against a saved recipe."}
      </p>
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
                    <span className="exception-text">
                      Substitutes for {l.substitutes_for}
                    </span>
                  )}
                </td>
                <td>
                  {l.quantity.requested_amount} {l.quantity.requested_unit}
                </td>
                <td>
                  {l.quantity.sales_quantity ?? "Unresolved"}{" "}
                  {l.quantity.sales_unit}
                  <span className="muted">
                    {l.quantity.proposed_amount} {l.quantity.requested_unit}
                  </span>
                  {Number(l.quantity.excess) > 0 && (
                    <span className="exception-text">
                      +{l.quantity.excess} excess
                    </span>
                  )}
                </td>
                <td>
                  {currency(l.gross)}
                  <span className="muted">Tax {currency(l.tax)}</span>
                  {Number(l.deposits_gross) > 0 && (
                    <span className="muted">
                      Deposits {currency(l.deposits_gross)}
                    </span>
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
              <span>{title(String(event.event))}</span>
              <span className="muted">
                {String(event.actor_id)} · {dateTime(String(event.created_at))}
              </span>
            </li>
          ))}
        </ol>
      </section>
      <details>
        <summary>Evidence and calculations</summary>
        <p>
          Observed {dateTime(p.snapshot.observed_at)}. Similarity and product
          names do not prove dietary or quantity requirements.
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
  );
}
