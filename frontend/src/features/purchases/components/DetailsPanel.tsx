import { useState } from "react";
import type { Proposal } from "../../../shared/api/types";
import { dateTime, title } from "../../../shared/lib/format";
import { PurchaseSheet } from "./PurchaseSheet";

type Source = { source?: { availability?: { closingTime?: unknown } } };

/** The earliest supplier order cut-off in the basket, when the lines carry one (commercial evidence). */
function cutOff(p: Proposal): string | null {
  const times = p.snapshot.lines
    .map(
      (l) =>
        (l.commercial_evidence as Source | undefined)?.source?.availability
          ?.closingTime,
    )
    .filter(
      (t): t is string => typeof t === "string" && !Number.isNaN(Date.parse(t)),
    )
    .sort();
  return times[0] ?? null;
}

/** When this revision was made: its event in the history, else the time its prices were checked. */
function revisionTime(p: Proposal): string {
  const made = [...(p.history ?? [])]
    .reverse()
    .find((e) =>
      ["proposal_prepared", "proposal_revised"].includes(String(e.event)),
    );
  return typeof made?.created_at === "string"
    ? made.created_at
    : p.snapshot.observed_at;
}

/**
 * The Details tab: facts about this order that the proposal already carries (reference, revision, how long the
 * prices hold, the supplier cut-off, the policy and approval state, whether substitutions are allowed), the history,
 * the sample notice and the full basket sheet. Rows without data are not drawn; nothing is invented.
 */
export function DetailsPanel({
  p,
  canConfirm,
  showEvidence,
  load,
}: {
  p: Proposal;
  canConfirm: boolean;
  showEvidence: boolean;
  load: () => Promise<void>;
}) {
  const [more, setMore] = useState(false);
  const cut = cutOff(p);
  const rows: { label: string; value: string }[] = [
    {
      label: "Order reference",
      value: p.order_id ?? p.proposal_id.slice(0, 8).toUpperCase(),
    },
    {
      label: "Revision",
      value: `${p.revision} · created ${dateTime(revisionTime(p))}`,
    },
    { label: "Prices valid until", value: dateTime(p.expires_at) },
    ...(cut ? [{ label: "Cut-off", value: dateTime(cut) }] : []),
    {
      label: "Policy",
      value: `v${p.policy_version} · approval ${title(p.approval_status).toLowerCase()}`,
    },
  ];
  return (
    <section className="flex flex-col gap-space-sm">
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-space-md gap-y-1 text-body-sm">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <dt className="m-0 font-label text-label-md text-secondary">
              {row.label}
            </dt>
            <dd className="m-0 break-words text-primary">{row.value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex items-center justify-between gap-space-sm text-body-sm">
        <span className="font-label text-label-md text-secondary">
          Allow substitutions
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={p.request.allow_substitution}
          aria-label="Allow substitutions"
          disabled
          className={`flex h-6 w-11 cursor-default items-center rounded-full border-0 p-0.5 ${p.request.allow_substitution ? "justify-end bg-wholesale-teal" : "justify-start bg-surface-container-high"}`}
        >
          <span
            aria-hidden="true"
            className="block h-5 w-5 rounded-full bg-surface-pure shadow-sm"
          />
        </button>
      </div>
      <p className="m-0 rounded bg-secondary-container/40 p-2 text-body-sm text-primary">
        {p.snapshot.mode === "fixture"
          ? "Catalog prices and stock for this basket."
          : "Supplier API evidence — rechecked before commitment."}{" "}
        Orders are recorded after your confirmation.
      </p>
      {canConfirm && (
        <p className="m-0 text-body-sm text-secondary">
          Your confirmation applies to revision {p.revision} only. We recheck
          prices, availability and your authority before recording the order.
          No supplier order or stock reservation is made.
        </p>
      )}
      {showEvidence && (
        <>
          <button
            type="button"
            aria-expanded={more}
            onClick={() => setMore((open) => !open)}
            className="cursor-pointer self-start border-0 bg-transparent px-0 font-label text-label-md font-bold text-wholesale-teal hover:underline"
          >
            More
          </button>
          {more && <PurchaseSheet p={p} />}
        </>
      )}
      <button
        type="button"
        onClick={load}
        className="cursor-pointer self-start border-0 bg-transparent px-0 font-label text-label-md font-bold text-wholesale-teal hover:underline"
      >
        Refresh status
      </button>
    </section>
  );
}
