import { useEffect, useId, useRef, useState } from "react";
import type { Proposal } from "../../../shared/api/types";

type Commercial = { tax_rate?: unknown };

/** "14" or "14.00" -> "14%". Mixed rates in one basket -> no number ("VAT"). From the proposal's lines, never computed. */
export function vatRate(p: Proposal): string {
  const rates = new Set(
    p.snapshot.lines
      .map((l) => (l.commercial_evidence as Commercial | undefined)?.tax_rate)
      .filter((r): r is string => typeof r === "string" && r !== ""),
  );
  if (rates.size !== 1) return "";
  const n = Number([...rates][0]);
  return Number.isFinite(n) ? `${Number(n.toFixed(2))}%` : "";
}

/** The breakdown is only shown when the proposal states every amount (an unresolved total shows none). */
export const hasBreakdown = (p: Proposal) =>
  p.snapshot.gross_total != null &&
  p.snapshot.net_total != null &&
  p.snapshot.tax_total != null &&
  !p.reasons.some((r) => r.code === "QUANTITY_UNRESOLVED");

/**
 * The VAT breakdown of the total: a circular "i" button on the right of the total row (aria-expanded,
 * aria-controls) and, when it is pressed, a small list directly under the total with Excl. VAT, VAT n%
 * and Total. Closed by default; a basket that is only updated keeps it as it is, a NEW basket closes it.
 * All amounts come from the proposal.
 */
export function useVatBreakdown(p: Proposal) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const seen = useRef(p.proposal_id);
  useEffect(() => {
    if (seen.current !== p.proposal_id) {
      seen.current = p.proposal_id;
      setOpen(false);
    }
  }, [p.proposal_id]);
  return {
    open,
    toggle: () => setOpen((o) => !o),
    id,
    available: hasBreakdown(p),
  };
}
