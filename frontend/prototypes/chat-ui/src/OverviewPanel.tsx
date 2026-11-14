import { useState } from "react";
import type { Conversation, Proposal } from "./types";
import { canConfirm, currency, statusOf, title } from "./shared";
import { useConfirmFlow } from "./confirmFlow";
import { useStagedProposal } from "./useStagedProposal";
import { store } from "./store";
import { MOCK } from "./mock";
import { Icon, InertButton } from "./placeholders";

// The Overview panel: the only place a buyer approves a purchase. A right-hand
// column on desktop, an expandable bottom drawer below 768px. It shows the
// proposal staged in the current conversation and runs the exact-revision
// confirm / reject (see confirmFlow.ts).

const BLOCKED_OUTCOMES = ["denied", "needs_resolution"];
const CLOSED_STATUSES = ["expired", "rejected", "superseded", "policy_changed"];

type Kind = "empty" | "receipt" | "closed" | "blocked" | "open";

function kindOf(p: Proposal | null): Kind {
  if (!p) return "empty";
  const s = statusOf(p);
  if (s === "accepted_mock") return "receipt";
  if (CLOSED_STATUSES.includes(s)) return "closed";
  if (!canConfirm(p)) return "blocked";
  return "open";
}

function AlertBox({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-space-sm rounded-lg bg-surface-container p-space-sm">
      <Icon name="notification_important" className="mt-0.5 shrink-0 text-[20px] text-wholesale-teal" />
      <div className="flex-1">
        <span className="block font-label text-label-md text-deep-ocean-navy">{heading}</span>
        <div className="font-body text-body-sm text-on-surface-variant">{children}</div>
      </div>
    </div>
  );
}

function StatusTag({ value }: { value: string }) {
  return (
    <span className="rounded-full bg-surface-container-high px-space-sm py-0.5 font-label text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">
      {title(value)}
    </span>
  );
}

function Items({ p }: { p: Proposal }) {
  return (
    <div className="flex flex-col gap-space-sm">
      <span className="font-label text-label-sm font-bold uppercase tracking-wider text-secondary">
        Ingredients &amp; staged items
      </span>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 font-body text-body-sm text-on-surface">
        {p.snapshot.lines.map((l) => (
          <li key={l.product_id} className="flex items-center justify-between gap-space-sm border-b border-border-subtle/50 py-1">
            <span>{l.name}</span>
            <span className="shrink-0 font-mono font-bold text-primary">
              {l.quantity.sales_quantity ?? "Unresolved"} {l.quantity.sales_unit}
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
        <span className="font-label text-label-lg font-bold text-primary">{currency(p.snapshot.gross_total)}</span>
        <span className="block text-[12px] text-secondary">
          Incl. VAT / {currency(p.snapshot.net_total)} excl. VAT
        </span>
      </div>
    </div>
  );
}

function Substitutions() {
  const on = MOCK.overview.substitutionsOn;
  return (
    <div className="flex items-center justify-between border-t border-border-subtle py-2">
      <span className="font-label text-label-sm font-bold text-primary">Substitutions</span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={MOCK.overview.substitutionsLabel}
        disabled
        className={`flex h-6 w-11 cursor-default items-center rounded-full border-0 p-0.5 ${on ? "justify-end bg-wholesale-teal" : "justify-start bg-surface-container-high"}`}
      >
        <span aria-hidden="true" className="block h-5 w-5 rounded-full bg-surface-pure shadow-sm" />
      </button>
    </div>
  );
}

function AccountManager() {
  const m = MOCK.overview.accountManager;
  return (
    <div className="flex items-center justify-between gap-space-sm rounded-xl bg-surface-container-low p-space-sm">
      <div className="flex min-w-0 items-center gap-space-sm">
        <span
          aria-hidden="true"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary font-label text-label-sm font-bold text-on-primary"
        >
          {m.initials}
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">Account Manager</span>
          <span className="truncate font-headline text-[13px] font-bold text-on-surface">{m.name}</span>
          <span className="truncate font-label text-[11px] text-on-surface-variant">{m.phone}</span>
        </span>
      </div>
      <InertButton
        label="Call account manager"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-pure text-primary shadow-level-2"
      >
        <Icon name="call" className="text-[16px]" />
      </InertButton>
    </div>
  );
}

const secondaryButton =
  "flex items-center justify-center gap-1 rounded-lg border-0 bg-surface-container px-space-sm py-2.5 font-label text-label-sm font-bold text-deep-ocean-navy";

function Decision({ p, onUpdate }: { p: Proposal; onUpdate: (p: Proposal) => void }) {
  const flow = useConfirmFlow(onUpdate);
  const kind = kindOf(p);
  const s = statusOf(p);

  async function viewCurrentRevision() {
    // Fixture-only stand-in for "the backend's next GET already returns the
    // latest revision" — see README.md known simplifications.
    store.advanceSuperseded(p.proposal_id);
    onUpdate(await store.getProposal(p.proposal_id));
  }

  if (kind === "receipt") {
    return (
      <div className="flex flex-col gap-space-sm rounded-lg border border-status-fresh-green bg-tertiary-fixed/40 p-space-sm">
        <div className="flex items-center gap-space-sm">
          <Icon name="check_circle" className="text-[24px] text-tertiary" />
          <strong className="font-headline text-headline-sm text-deep-ocean-navy">Order accepted</strong>
        </div>
        {flow.message && (
          <p role="status" className="m-0 font-body text-body-sm text-on-surface">
            {flow.message}
          </p>
        )}
        <p className="m-0 font-body text-body-sm text-on-surface">
          Accepted by demo order service. No real supplier order was placed.
        </p>
        <p className="m-0 break-all font-mono text-body-sm font-bold text-primary">Order {p.order_id}</p>
      </div>
    );
  }

  const outcome = flow.message && !flow.revised && (
    <p role="status" className="m-0 font-body text-body-sm text-on-surface">
      {flow.message}
    </p>
  );

  if (kind === "closed") {
    return (
      <div className="flex flex-col gap-space-sm">
        {outcome}
        {s === "superseded" && (
          <p className="m-0 font-body text-body-sm text-on-surface-variant">
            These terms were superseded.{" "}
            <button
              type="button"
              onClick={() => void viewCurrentRevision()}
              className="cursor-pointer border-0 bg-transparent p-0 font-[inherit] font-bold text-wholesale-teal underline"
            >
              View current revision {p.current_revision}
            </button>
          </p>
        )}
        {s !== "superseded" && (
          <p className="m-0 font-body text-body-sm text-on-surface-variant">This revision is closed for decisions.</p>
        )}
      </div>
    );
  }

  if (kind === "blocked") {
    return (
      <div className="flex flex-col gap-space-sm">
        <AlertBox heading={BLOCKED_OUTCOMES.includes(p.policy_outcome) ? "This purchase cannot be approved" : "Approval needed"}>
          {p.reasons.length > 0 && BLOCKED_OUTCOMES.includes(p.policy_outcome) ? (
            <ul className="m-0 list-none p-0">
              {p.reasons.map((r) => (
                <li key={r.code}>{r.message}</li>
              ))}
            </ul>
          ) : (
            "Your account does not have authority for this amount or exception."
          )}
        </AlertBox>
        {outcome}
      </div>
    );
  }

  // open
  return (
    <div className="flex flex-col gap-space-xs">
      {flow.revised && (
        <AlertBox heading="Terms changed during verification">
          Review the new revision and confirm again.
        </AlertBox>
      )}
      {flow.error && <AlertBox heading="Could not complete the action">{flow.error}</AlertBox>}
      {outcome}
      <button
        type="button"
        disabled={flow.busy}
        onClick={() => void flow.confirm(p)}
        className="flex w-full cursor-pointer items-center justify-center gap-space-xs rounded-lg border-0 bg-status-fresh-green px-space-md py-3 font-label text-label-lg font-bold text-deep-ocean-navy shadow-sm hover:brightness-95 disabled:cursor-wait disabled:opacity-70"
      >
        <Icon name="local_shipping" className="text-[20px]" />
        {flow.busy ? "Verifying purchase…" : "Approve & Push to Dispatch"}
      </button>
      <div className="grid grid-cols-2 gap-space-xs">
        {p.can_decide && s === "pending" ? (
          <button
            type="button"
            disabled={flow.busy}
            onClick={() => void flow.reject(p)}
            className="cursor-pointer rounded-lg border border-error bg-transparent px-space-sm py-2.5 font-label text-label-sm font-bold text-error hover:bg-error-container disabled:opacity-70"
          >
            Reject
          </button>
        ) : (
          <span />
        )}
        <InertButton label="Save as Draft" className={secondaryButton}>
          <Icon name="bookmark_border" className="text-[16px]" />
          Save as Draft
        </InertButton>
      </div>
    </div>
  );
}

export function OverviewPanel({ conversation }: { conversation: Conversation | null }) {
  const { proposal: p, setProposal } = useStagedProposal(conversation);
  const [open, setOpen] = useState(false);
  const kind = kindOf(p);
  const grey = kind === "closed";
  const count = p?.snapshot.lines.length ?? 0;

  return (
    <aside
      aria-label="Overview"
      data-overview-panel
      className="fixed inset-x-3 bottom-24 z-30 flex max-h-[70vh] flex-col overflow-y-auto rounded-2xl border border-border-subtle bg-surface-pure p-space-md shadow-level-3 md:inset-x-auto md:bottom-16 md:right-0 md:top-[86px] md:max-h-none md:w-[380px] md:rounded-none md:border-y-0 md:border-r-0 md:shadow-none"
    >
      <div className="flex items-center justify-between gap-space-sm border-b border-border-subtle pb-space-sm">
        <h2 className="m-0 font-headline text-headline-sm font-bold text-primary">Overview</h2>
        <span className="flex items-center gap-space-sm">
          {p && grey && <StatusTag value={statusOf(p)} />}
          <span className="font-label text-label-sm text-secondary">{p ? `${count} items staged` : "Nothing staged"}</span>
          <button
            type="button"
            aria-label={open ? "Collapse overview" : "Expand overview"}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-secondary hover:bg-surface-container md:hidden"
          >
            <Icon name={open ? "keyboard_arrow_down" : "keyboard_arrow_up"} className="text-[18px]" />
          </button>
        </span>
      </div>
      <div className="flex flex-col gap-space-sm pt-space-sm">
        {!p ? (
          <p className={`m-0 font-body text-body-sm text-on-surface-variant ${open ? "" : "hidden md:block"}`}>
            No items staged yet. Describe a meal or an ingredient list and the proposed basket appears here.
          </p>
        ) : (
          <>
            <div className={`${open ? "flex" : "hidden"} flex-col gap-space-sm md:flex ${grey ? "opacity-60" : ""}`}>
              <Items p={p} />
              {kind !== "receipt" && <Substitutions />}
            </div>
            <div className={grey ? "opacity-60" : ""}>
              <Total p={p} />
            </div>
            <div className={`${open ? "flex" : "hidden"} flex-col gap-space-sm md:flex`}>
              <Decision p={p} onUpdate={setProposal} />
              <InertButton label="Export Manifest" className={`${secondaryButton} w-full`}>
                <Icon name="file_download" className="text-[16px]" />
                Export Manifest
              </InertButton>
            </div>
          </>
        )}
        <div className={`${open ? "block" : "hidden"} md:block`}>
          <AccountManager />
        </div>
      </div>
    </aside>
  );
}
