import type { ScheduleLine } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { percentLabel } from "../model/scheduleStatus";

// The agreed lines: what is delivered each run, at which price, and which substitutes the
// customer accepted with the price range they allow.
export function ScheduleLines({
  lines,
  currencyCode,
}: {
  lines: ScheduleLine[];
  currencyCode?: string | null;
}) {
  const eur = currencyCode ?? "EUR";
  if (lines.length === 0)
    return <p className="m-0 text-secondary">No lines on this order.</p>;
  return (
    <ul className="m-0 flex list-none flex-col divide-y divide-border-subtle p-0">
      {lines.map((line) => (
        <li
          key={line.product_id}
          className="flex flex-col gap-space-xs py-space-sm first:pt-0 last:pb-0"
        >
          <div className="flex flex-col gap-space-xs sm:flex-row sm:items-baseline sm:justify-between">
            <span className="font-label text-label-lg text-primary">
              {line.name}
            </span>
            <span className="font-label text-label-lg text-primary">
              {currency(line.line_gross, eur)}
            </span>
          </div>
          <p className="m-0 text-body-sm text-on-surface-variant">
            {line.amount} {line.unit} · {currency(line.unit_gross, eur)} per{" "}
            {line.unit} incl. tax
          </p>
          {(line.accepted_substitutes?.length ?? 0) > 0 && (
            <div className="rounded-lg bg-surface-container-low px-space-md py-space-sm text-body-sm text-on-surface-variant">
              <p className="m-0 font-label text-label-sm uppercase">
                Accepted substitutes · price range{" "}
                {percentLabel(line.price_range_pct)}
              </p>
              {line.accepted_substitutes?.map((sub) => (
                <p key={sub.product_id} className="m-0">
                  {sub.name} · {currency(sub.unit_gross, eur)}
                </p>
              ))}
            </div>
          )}
          {(line.accepted_substitutes?.length ?? 0) === 0 &&
            Number(line.price_range_pct ?? 0) > 0 && (
              <p className="m-0 text-body-sm text-on-surface-variant">
                Accepted price range {percentLabel(line.price_range_pct)}
              </p>
            )}
        </li>
      ))}
    </ul>
  );
}
