// Past Orders (routes "/purchases" and "/purchases/:proposalId"): accepted
// orders only, as rows that expand in place. The purchase list endpoint returns
// every proposal, so the filter runs here and pages are fetched until a page of
// accepted orders is filled or the list ends. /purchases/:id expands that row
// and scrolls it into view, or explains that the purchase isn't placed yet.
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import type { Proposal } from "./types";
import { currency, dateTime } from "./shared";
import { store } from "./store";
import { MOCK } from "./mock";
import { Icon, InertButton, InertInput } from "./placeholders";

const PAGE_SIZE = 5;

const isAccepted = (p: Proposal) => Boolean(p.order_id) && p.order_status === "accepted_mock";

const placedAt = (p: Proposal) =>
  p.history?.find((e) => e.event === "purchase_confirmed")?.created_at ?? p.snapshot.observed_at;

const NOT_PLACED = "This purchase hasn't been placed yet — confirm it in the request it came from";

export function PurchasesPage() {
  const { proposalId } = useParams();
  const [orders, setOrders] = useState<Proposal[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const scrolled = useRef(false);

  // Fetch API pages until `want` accepted orders are held (and `mustHave`, if
  // given, is among them) or the list ends.
  const fill = useCallback(async (from: number, held: Proposal[], want: number, mustHave?: string) => {
    let offset: number | null = from;
    let all = held;
    while (offset !== null) {
      const page = await store.listPurchases(offset);
      all = [...all, ...page.items.filter(isAccepted)];
      offset = page.next_offset;
      if (all.length >= want && (!mustHave || all.some((p) => p.proposal_id === mustHave))) break;
    }
    setOrders(all);
    setNextOffset(offset);
  }, []);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        let target: string | undefined;
        if (proposalId) {
          try {
            const p = await store.getProposal(proposalId);
            if (isAccepted(p)) {
              target = p.proposal_id;
              setExpanded(new Set([p.proposal_id]));
            } else setNotice(NOT_PLACED);
          } catch {
            setNotice(NOT_PLACED);
          }
        }
        if (live) await fill(0, [], PAGE_SIZE, target);
      } catch (e) {
        if (live) setError((e as Error).message);
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [proposalId, fill]);

  useEffect(() => {
    if (!proposalId || loading || scrolled.current) return;
    scrolled.current = true;
    document.getElementById(`order-${proposalId}`)?.scrollIntoView({ block: "center" });
  }, [proposalId, loading, orders]);

  const showMore = async () => {
    if (nextOffset === null) return;
    setLoading(true);
    try {
      await fill(nextOffset, orders, orders.length + PAGE_SIZE);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const m = MOCK.pastOrders;
  return (
    <main>
      <section className="border-b border-border-subtle bg-surface-pure px-margin-sm py-space-lg md:px-margin md:py-space-xl">
        <div className="mx-auto flex max-w-6xl flex-col justify-between gap-space-md md:flex-row md:items-end">
          <h1 className="m-0 font-headline text-headline-lg-mobile tracking-normal text-primary md:text-headline-lg">
            Past Orders
          </h1>
          <div className="flex items-center gap-space-sm rounded-lg bg-surface-container-low px-space-md py-space-sm">
            <Icon name="verified" className="text-wholesale-teal" />
            <div>
              <div className="font-label text-label-sm uppercase text-secondary">{m.account.label}</div>
              <div className="font-label text-label-md text-primary">{m.account.value}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="px-margin-sm py-space-lg md:px-margin">
        <div className="mx-auto flex max-w-6xl flex-col gap-space-md lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Icon name="search" className="absolute left-space-md top-1/2 -translate-y-1/2 text-secondary" />
            <InertInput
              label={m.searchLabel}
              placeholder={m.searchPlaceholder}
              className="w-full rounded-lg border-0 bg-surface-pure py-3 pl-11 pr-space-md font-body text-body-md text-on-surface shadow-level-2"
            />
          </div>
          <div className="flex flex-wrap items-center gap-space-sm">
            {[m.periodLabel, m.sortLabel, m.statusLabel].map((label) => (
              <InertButton
                key={label}
                label={label}
                className="rounded-lg !bg-surface-pure px-space-md py-3 font-label text-label-md text-on-surface shadow-level-2"
              >
                {label}
              </InertButton>
            ))}
          </div>
        </div>
      </section>

      <section className="px-margin-sm pb-space-xl md:px-margin">
        <div className="mx-auto flex max-w-6xl flex-col gap-space-md">
          {notice && (
            <div
              role="status"
              className="flex items-start gap-space-sm rounded-lg border border-outline-variant bg-surface-container-low p-space-md font-body text-body-md text-on-surface"
            >
              <Icon name="info" className="text-wholesale-teal" />
              <span>{notice}</span>
            </div>
          )}
          {error && (
            <div role="alert" className="rounded-lg bg-error-container p-space-md text-on-error-container">
              {error}
            </div>
          )}
          {orders.map((p) => {
            const open = expanded.has(p.proposal_id);
            const title = p.request.request_id;
            return (
              <article
                key={p.proposal_id}
                id={`order-${p.proposal_id}`}
                className="scroll-mt-space-lg rounded-xl bg-surface-pure p-space-md shadow-level-2 md:p-space-lg"
              >
                <div className="flex flex-col justify-between gap-space-md lg:flex-row lg:items-center">
                  <div className="flex flex-1 flex-col gap-space-xs">
                    <div className="flex flex-wrap items-center gap-space-sm font-label text-label-sm text-secondary">
                      <span className="rounded bg-surface-container-high px-2 py-0.5 font-bold uppercase text-primary">
                        {p.order_id}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-full bg-status-fresh-green/20 px-2 py-0.5 font-bold text-primary">
                        <span aria-hidden="true" className="inline-block size-2 rounded-full bg-status-fresh-green" />
                        Accepted (demo)
                      </span>
                      <span>{dateTime(placedAt(p))}</span>
                    </div>
                    <h2 className="m-0 font-headline text-headline-sm text-primary">{title}</h2>
                    <div className="font-body text-body-sm text-on-surface-variant">
                      {p.snapshot.lines.length} {p.snapshot.lines.length === 1 ? "item" : "items"} · {p.request.destination}
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-space-md lg:justify-end">
                    <div className="lg:text-right">
                      <div className="font-headline text-headline-md font-bold text-primary">
                        <span>{currency(p.snapshot.gross_total)}</span>{" "}
                        <span className="font-label text-label-sm font-normal text-secondary">incl. VAT</span>
                      </div>
                      <div className="font-label text-label-sm text-secondary">
                        {currency(p.snapshot.net_total)} excl. VAT
                      </div>
                    </div>
                    <button
                      type="button"
                      aria-label={`Order details: ${title}`}
                      aria-expanded={open}
                      aria-controls={`details-${p.proposal_id}`}
                      onClick={() => toggle(p.proposal_id)}
                      className="cursor-pointer rounded-lg border-0 bg-surface-container-low p-3 text-primary hover:bg-surface-container-high"
                    >
                      <Icon name={open ? "expand_less" : "expand_more"} />
                    </button>
                  </div>
                </div>
                {open && (
                  <div
                    id={`details-${p.proposal_id}`}
                    className="mt-space-md flex flex-col gap-space-sm rounded-lg bg-surface-container-low p-space-md"
                  >
                    <div className="font-label text-label-md uppercase tracking-wider text-secondary">
                      Ordered items
                    </div>
                    <ul className="m-0 grid list-none grid-cols-1 gap-space-sm p-0 font-body text-body-sm text-on-surface md:grid-cols-3">
                      {p.snapshot.lines.map((l) => (
                        <li key={l.product_id} className="rounded bg-surface-pure p-space-sm">
                          {l.name} (x{l.quantity.proposed_amount} {l.quantity.requested_unit})
                        </li>
                      ))}
                    </ul>
                    <div className="font-label text-label-sm text-secondary">
                      Delivery to {p.request.destination} on {p.request.delivery_date} · Accepted by demo order service
                    </div>
                  </div>
                )}
              </article>
            );
          })}
          {loading && (
            <p role="status" className="m-0 py-space-lg text-center text-secondary">
              Loading past orders…
            </p>
          )}
          {!loading && !error && orders.length === 0 && (
            <section className="rounded-xl bg-surface-pure p-space-xl text-center">
              <h2 className="m-0 font-headline text-headline-sm text-primary">No past orders yet</h2>
              <p className="text-secondary">Orders you approve in a request will appear here.</p>
            </section>
          )}
          {!loading && nextOffset !== null && (
            <button
              type="button"
              onClick={showMore}
              className="cursor-pointer self-center rounded-lg border border-outline-variant bg-surface-pure px-space-lg py-3 font-label text-label-md text-primary hover:bg-surface-container-high"
            >
              Show more orders
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
