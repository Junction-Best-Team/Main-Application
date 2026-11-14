import type { ScheduleTerms } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { cadenceLabel, formatDate } from "../model/scheduleStatus";
import { card, cardTitle, hint, label } from "./formStyles";

// The exact terms the customer is asked to agree to. Read-only: every figure comes from the
// preview, nothing is computed here.
export function TermsSummary({
  terms,
  reasons,
  notReady,
}: {
  terms: ScheduleTerms;
  reasons: string[];
  notReady: boolean;
}) {
  const money = (v: string | null | undefined) =>
    currency(v, terms.currency ?? "EUR");
  return (
    <section aria-labelledby="terms-heading" className={card}>
      <div className="flex flex-col gap-1">
        <h2 id="terms-heading" className={cardTitle}>
          Terms
        </h2>
        <p className="m-0 font-body text-body-md text-on-surface wrap-anywhere">
          {terms.title}
        </p>
      </div>

      {notReady && (
        <div className="rounded-lg bg-error-container p-space-md text-on-error-container">
          <p className="m-0 font-label text-label-lg">
            This standing order cannot be created as it stands.
          </p>
          {reasons.length > 0 && (
            <ul className="m-0 mt-space-xs list-disc pl-space-lg font-body text-body-sm">
              {reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <ul className="m-0 flex list-none flex-col divide-y divide-border-subtle p-0">
        {terms.lines.map((line) => (
          <li
            key={line.product_id}
            className="flex flex-wrap items-baseline justify-between gap-x-space-md gap-y-1 py-space-sm"
          >
            <div className="min-w-0">
              <div className="font-body text-body-md text-on-surface wrap-anywhere">
                {line.name}
              </div>
              <div className={hint}>
                {line.amount} {line.unit}
                {line.unit_gross != null &&
                  ` · ${money(line.unit_gross)} per ${line.sales_unit ?? "unit"}`}
              </div>
            </div>
            <div className="font-label text-label-lg text-primary">
              {money(line.line_gross)}
            </div>
          </li>
        ))}
      </ul>

      <div className="flex items-baseline justify-between gap-space-md border-t border-border-subtle pt-space-sm">
        <span className={label}>Gross total per run</span>
        <span className="font-headline text-headline-sm text-primary">
          {money(terms.gross_total)}
        </span>
      </div>

      <dl className="m-0 grid grid-cols-1 gap-space-sm sm:grid-cols-2">
        <div>
          <dt className={label}>Repeats</dt>
          <dd className="m-0 font-body text-body-md">
            {cadenceLabel(terms.recurrence)}
          </dd>
        </div>
        <div>
          <dt className={label}>Valid until</dt>
          <dd className="m-0 font-body text-body-md">
            {formatDate(terms.valid_until)}
          </dd>
        </div>
        <div>
          <dt className={label}>Delivery</dt>
          <dd className="m-0 font-body text-body-md">
            {terms.delivery_offset_days === 1
              ? "1 day after each run"
              : `${terms.delivery_offset_days} days after each run`}
          </dd>
        </div>
        <div>
          <dt className={label}>First runs</dt>
          <dd className="m-0">
            <ul className="m-0 list-none p-0 font-body text-body-md">
              {terms.next_dates.map((d) => (
                <li key={d}>{formatDate(d)}</li>
              ))}
            </ul>
          </dd>
        </div>
      </dl>
    </section>
  );
}
