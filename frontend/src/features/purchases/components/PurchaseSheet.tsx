import type { Proposal } from "../../../shared/api/types";
import { currency, dateTime, title } from "../../../shared/lib/format";
export function PurchaseSheet({ p }: { p: Proposal }) {
  return (
    <article className="purchase-sheet min-w-0 rounded-xl border border-border-subtle bg-surface-pure p-4 md:p-6 [&_h2]:text-headline-sm">
      <div className="mb-6 grid grid-cols-1 gap-4 border-b border-border-subtle pb-6 sm:grid-cols-2 [&_span]:mb-1 [&_span]:block [&_span]:font-label [&_span]:text-label-md [&_span]:text-secondary [&_strong]:block [&_strong]:wrap-anywhere [&_strong]:text-body-sm [&_strong]:text-primary">
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
      <p className="mode-note mb-6 rounded-lg border border-border-subtle bg-secondary-container/40 px-4 py-3 text-body-sm text-primary">
        {p.recipe_basis === "saved_recipe"
          ? "Recipe-backed basket — includes every ingredient from the saved recipe plan."
          : "Free-form basket — recipe completeness and ingredient conversions are not checked against a saved recipe."}
      </p>
      <div className="table-scroll max-w-full overflow-x-auto [&_table]:w-full [&_table]:border-collapse [&_table]:text-left [&_table]:text-body-sm [&_th]:border-b [&_th]:border-border-subtle [&_th]:bg-surface-container-low [&_th]:px-3 [&_th]:py-3 [&_th]:font-label [&_th]:text-label-md [&_th]:font-semibold [&_th]:text-secondary [&_td]:border-b [&_td]:border-border-subtle [&_td]:px-3 [&_td]:py-4 [&_td]:align-top [&_td:first-child]:min-w-44 [&_td:last-child]:text-right [&_td_span]:mt-1 [&_td_span]:block [&_td_span]:text-label-sm">
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
                  <span className="text-secondary">Product {l.product_id}</span>
                  {l.substitutes_for && (
                    <span className="text-amber-800 dark:text-amber-200">
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
                  <span className="text-secondary">
                    {l.quantity.proposed_amount} {l.quantity.requested_unit}
                  </span>
                  {Number(l.quantity.excess) > 0 && (
                    <span className="text-amber-800 dark:text-amber-200">
                      +{l.quantity.excess} excess
                    </span>
                  )}
                </td>
                <td>
                  {currency(l.gross)}
                  <span className="text-secondary">Tax {currency(l.tax)}</span>
                  {Number(l.deposits_gross) > 0 && (
                    <span className="text-secondary">
                      Deposits {currency(l.deposits_gross)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="my-6 ml-auto max-w-sm rounded-lg bg-surface-container-low p-4 [&>div]:flex [&>div]:justify-between [&>div]:gap-4 [&>div]:py-1 [&>div]:text-body-sm [&>div>span:last-child]:font-label">
        <div>
          <span>Deposits (included)</span>
          <span>{currency(p.snapshot.deposits_gross)}</span>
        </div>
        <div>
          <span>Demo delivery charges</span>
          <span>{currency(p.snapshot.charges_gross)}</span>
        </div>
        <div className="mt-3 border-t border-border-subtle pt-4! font-bold text-primary">
          <strong>Gross payable</strong>
          <strong>{currency(p.snapshot.gross_total)}</strong>
        </div>
      </div>
      <section className="border-t border-border-subtle pt-6 [&_ol]:list-none [&_ol]:p-0 [&_li]:my-3 [&_li]:flex [&_li]:flex-col [&_li]:justify-between [&_li]:gap-1 [&_li]:text-body-sm md:[&_li]:flex-row md:[&_li]:gap-4">
        <h2>Decision history</h2>
        <ol>
          {(p.history ?? []).map((event, i) => (
            <li key={i}>
              <span>{title(String(event.event))}</span>
              <span className="text-secondary">
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
