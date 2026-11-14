import { useState } from "react";
import type { Proposal } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { Icon, InertButton } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { Badge } from "../../../shared/components/Badge";
import { getPurchaseStatus } from "../model/purchaseStatus";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { PurchaseDecisionPanel } from "./PurchaseDecisionPanel";
import { PurchaseSheet } from "./PurchaseSheet";
function Items({ p }: { p: Proposal }) {
  return (
    <div className="flex flex-col gap-space-sm">
      <span className="font-label text-label-sm font-bold uppercase tracking-wider text-secondary">
        Ingredients &amp; staged items
      </span>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 font-body text-body-sm text-on-surface">
        {p.snapshot.lines.map((l) => (
          <li
            key={l.product_id}
            className="flex items-center justify-between gap-space-sm border-b border-border-subtle/50 py-1"
          >
            <span>{l.name}</span>
            <span className="shrink-0 font-mono font-bold text-primary">
              {l.quantity.sales_quantity ?? "Unresolved"}{" "}
              {l.quantity.sales_unit}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Total({ p }: { p: Proposal }) {
  return (
    <div className="flex items-baseline justify-between gap-space-sm">
      <span className="font-label text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">
        Total estimated
      </span>
      <div className="text-right font-mono">
        <span className="font-label text-label-lg font-bold text-primary">
          {currency(p.snapshot.gross_total)}
        </span>
        <span className="block text-[12px] text-secondary">
          Incl. VAT / {currency(p.snapshot.net_total)} excl. VAT
        </span>
      </div>
    </div>
  );
}

function Substitutions({ p }: { p: Proposal }) {
  const on = p.request.allow_substitution;
  return (
    <div className="flex items-center justify-between border-t border-border-subtle py-2">
      <span className="font-label text-label-sm font-bold text-primary">
        Substitutions
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={MOCK.overview.substitutionsLabel}
        disabled
        className={`flex h-6 w-11 cursor-default items-center rounded-full border-0 p-0.5 ${on ? "justify-end bg-wholesale-teal" : "justify-start bg-surface-container-high"}`}
      >
        <span
          aria-hidden="true"
          className="block h-5 w-5 rounded-full bg-surface-pure shadow-sm"
        />
      </button>
    </div>
  );
}

export function OverviewPanel({
  flow,
  drawer = true,
  showEvidence = true,
}: {
  flow: ReturnType<typeof usePurchaseDetail>;
  drawer?: boolean;
  showEvidence?: boolean;
}) {
  const { p, error } = flow;
  const [open, setOpen] = useState(false);
  const closed =
    p &&
    ["expired", "rejected", "superseded", "policy_changed"].includes(
      getPurchaseStatus(p),
    );
  return (
    <aside
      id="overview"
      aria-label="Overview"
      className={`${drawer ? "fixed inset-x-3 bottom-4 z-30 max-h-[70dvh] lg:sticky lg:inset-x-auto lg:bottom-auto lg:top-0 lg:z-auto lg:max-h-full lg:w-80 lg:shrink-0 xl:w-96" : "w-full"} flex min-w-0 flex-col overflow-y-auto rounded-xl border border-border-subtle bg-surface-pure p-space-md shadow-level-3 lg:shadow-sm`}
    >
      <div className="flex items-center justify-between gap-space-sm border-b border-border-subtle pb-space-sm">
        <h2 className="m-0 font-headline text-headline-sm font-bold text-primary">
          Overview
        </h2>
        <span className="flex items-center gap-space-sm">
          <span className="font-label text-label-sm text-secondary">
            {p
              ? `${p.snapshot.lines.length} items staged`
              : error
                ? "Basket unavailable"
                : "Loading basket…"}
          </span>
          {drawer && (
            <button
              type="button"
              aria-label={open ? "Collapse overview" : "Expand overview"}
              aria-expanded={open}
              onClick={() => setOpen(!open)}
              className="flex h-9 w-9 items-center justify-center rounded-lg border-0 bg-transparent p-0 text-secondary lg:hidden"
            >
              <Icon name={open ? "keyboard_arrow_down" : "keyboard_arrow_up"} />
            </button>
          )}
        </span>
      </div>
      <ErrorMessage message={error} />
      <div className="flex flex-col gap-space-sm pt-space-sm">
        {!p ? (
          !error && (
            <p
              role="status"
              className={`m-0 text-body-sm text-on-surface-variant ${drawer && !open ? "hidden lg:block" : ""}`}
            >
              Loading the proposed basket…
            </p>
          )
        ) : (
          <>
            <div
              className={`${drawer && !open ? "hidden lg:flex" : "flex"} flex-col gap-space-sm ${closed ? "opacity-60" : ""}`}
            >
              <Badge value={getPurchaseStatus(p)} />
              <span className="font-label text-label-sm text-secondary">
                Revision {p.revision} / v{p.policy_version}
              </span>
              <Items p={p} />
              {!p.order_id && <Substitutions p={p} />}
            </div>
            <div className={closed ? "opacity-60" : ""}>
              <Total p={p} />
            </div>
            <div
              className={`${drawer && !open ? "hidden lg:flex" : "flex"} flex-col gap-space-sm`}
            >
              <p className="m-0 rounded bg-secondary-container/40 p-2 text-body-sm text-primary">
                {p.snapshot.mode === "fixture"
                  ? "Fixture prices and stock — invented for a repeatable demo."
                  : "Supplier API evidence — rechecked before demo commitment."}{" "}
                Orders are accepted by the demo service only.
              </p>
              {showEvidence && (
                <details className="mt-0">
                  <summary>Basket quantities, evidence and history</summary>
                  <PurchaseSheet p={p} />
                </details>
              )}
              <PurchaseDecisionPanel {...flow} p={p} />
              <InertButton
                label="Export Manifest"
                className="flex w-full items-center justify-center gap-1 rounded-lg bg-surface-container px-space-sm py-2.5 font-label text-label-sm font-bold text-deep-ocean-navy"
              >
                <Icon name="file_download" />
                Export Manifest
              </InertButton>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
