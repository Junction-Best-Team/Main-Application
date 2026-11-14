import type { Proposal } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
// Net (excl. VAT) is gross minus the line's VAT, computed in cents.
function netOf(line: Proposal["snapshot"]["lines"][number]) {
  const cents =
    Math.round(Number(line.gross) * 100) - Math.round(Number(line.tax) * 100);
  return (cents / 100).toFixed(2);
}

export function SkuCards({ proposal }: { proposal?: Proposal }) {
  const lines = proposal?.snapshot.lines;
  if (!lines?.length) return null;
  return (
    <ul
      aria-label="Proposed items"
      className="m-0 mt-space-md list-none p-0 grid grid-cols-1 gap-space-sm md:grid-cols-2"
    >
      {lines.map((line) => (
        <li
          key={line.product_id}
          className="flex flex-col justify-between rounded-lg bg-surface-pure p-space-sm shadow-sm"
        >
          <div className="flex items-start justify-between gap-space-xs">
            <div className="min-w-0">
              <span className="mb-1 inline-block rounded bg-primary-fixed px-1.5 py-0.5 font-label text-label-sm font-bold text-on-primary-fixed">
                SKU {line.product_id}
              </span>
              <h3 className="text-[16px] font-bold leading-tight text-primary">
                {line.name}
              </h3>
              {line.substitutes_for && (
                <span className="font-label text-label-sm text-secondary">
                  Substitute for {line.substitutes_for}
                </span>
              )}
            </div>
            <span className="whitespace-nowrap font-mono text-label-lg font-bold text-primary">
              {line.quantity.sales_quantity ?? "Unresolved"}{" "}
              {line.quantity.sales_unit}
            </span>
          </div>
          <div className="mt-space-sm flex items-center justify-between gap-space-xs rounded bg-surface-container-low px-2 py-1">
            <span className="flex items-baseline gap-1">
              <span className="text-[16px] font-bold text-primary">
                {currency(netOf(line))}
              </span>
              <span className="font-label text-label-sm text-secondary">
                excl. VAT
              </span>
            </span>
            <span className="font-label text-label-sm text-secondary">
              <span className="font-bold">{currency(line.gross)}</span> incl.
              VAT
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
