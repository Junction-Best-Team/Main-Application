import type { ScheduleRun } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { RUN_LINE_LABEL } from "../model/scheduleStatus";

type RunLine = NonNullable<ScheduleRun["substitutions"]>[number];

const PROBLEM = new Set([
  "price_outside_range",
  "unavailable",
  "withdrawn",
  "blocked_by_policy",
]);

// One line of a run: its status, agreed versus current price, and the substitute used if any.
export function RunLineStatus({
  line,
  currencyCode,
}: {
  line: RunLine;
  currencyCode?: string | null;
}) {
  const eur = currencyCode ?? "EUR";
  const hasPrices = line.agreed_gross != null && line.current_gross != null;
  return (
    <div
      data-testid="run-line"
      className="flex flex-col gap-1 rounded-lg bg-surface-container-low px-space-md py-space-sm"
    >
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
        <span className="font-label text-label-md text-primary">
          {line.name ?? line.product_id}
        </span>
        <span
          className={`font-label text-label-sm font-bold ${PROBLEM.has(line.status) ? "text-error" : "text-on-surface-variant"}`}
        >
          {RUN_LINE_LABEL[line.status] ?? line.status}
        </span>
      </div>
      {hasPrices && (
        <p className="m-0 text-body-sm text-on-surface-variant">
          {`Agreed ${currency(line.agreed_gross, eur)} · now ${currency(line.current_gross, eur)}`}
        </p>
      )}
      {line.substitute_product_id && (
        <p className="m-0 text-body-sm text-on-surface-variant">
          {`Substituted by product ${line.substitute_product_id}`}
          {line.note ? ` · ${line.note}` : ""}
        </p>
      )}
      {!line.substitute_product_id && line.note && (
        <p className="m-0 text-body-sm text-on-surface-variant">{line.note}</p>
      )}
    </div>
  );
}
