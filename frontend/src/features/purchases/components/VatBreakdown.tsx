import type { Proposal } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { vatRate, type useVatBreakdown } from "../hooks/useVatBreakdown";

export function VatButton({
  state,
}: {
  state: ReturnType<typeof useVatBreakdown>;
}) {
  if (!state.available) return null;
  return (
    <button
      type="button"
      aria-label="VAT breakdown"
      aria-expanded={state.open}
      aria-controls={state.id}
      onClick={state.toggle}
      className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-outline-variant bg-surface-pure p-0 font-headline text-label-sm font-bold italic text-secondary"
    >
      i
    </button>
  );
}

export function VatDetails({
  p,
  state,
}: {
  p: Proposal;
  state: ReturnType<typeof useVatBreakdown>;
}) {
  const unit = p.snapshot.currency ?? "EUR";
  const rate = vatRate(p);
  const row = (label: string, value: string | null, strong = false) => (
    <div
      className={`flex justify-between gap-space-sm ${strong ? "font-bold text-primary" : ""}`}
    >
      <dt className="m-0">{label}</dt>
      <dd className="m-0 font-mono">{currency(value, unit)}</dd>
    </div>
  );
  const nonZero = (v: string | null | undefined) =>
    v != null && Number(v) !== 0;
  return (
    <dl
      id={state.id}
      data-testid="card-vat"
      hidden={!state.open || !state.available}
      className="m-0 flex flex-col gap-1 rounded-lg bg-surface-container-low px-3 py-2 text-label-sm text-secondary"
    >
      {row("Excl. VAT", p.snapshot.net_total)}
      {row(rate ? `VAT ${rate}` : "VAT", p.snapshot.tax_total)}
      {nonZero(p.snapshot.deposits_gross) &&
        row("Deposits", p.snapshot.deposits_gross)}
      {nonZero(p.snapshot.charges_gross) &&
        row("Charges", p.snapshot.charges_gross)}
      {row("Total", p.snapshot.gross_total, true)}
    </dl>
  );
}
