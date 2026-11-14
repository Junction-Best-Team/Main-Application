import type { Proposal } from "../../../shared/api/types";
import { currency, dateTime } from "../../../shared/lib/format";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { placedAt } from "../model/acceptedOrders";
import { PurchaseSheet } from "./PurchaseSheet";
export function PurchaseList({
  orders,
  expanded,
  toggle,
}: {
  orders: Proposal[];
  expanded: Set<string>;
  toggle: (id: string) => void;
}) {
  return (
    <>
      {" "}
      {orders.map((p) => {
        const open = expanded.has(p.proposal_id);
        const title = p.request.request_id;
        return (
          <article
            key={p.proposal_id}
            id={`order-${p.proposal_id}`}
            className="purchase-row min-w-0 scroll-mt-space-lg rounded-xl bg-surface-pure p-space-md shadow-level-2 md:p-space-lg"
          >
            <div className="flex flex-col justify-between gap-space-md lg:flex-row lg:items-center">
              <div className="flex flex-1 flex-col gap-space-xs">
                <div className="flex flex-wrap items-center gap-space-sm font-label text-label-sm text-secondary">
                  <span className="order-reference rounded bg-surface-container-high px-2 py-0.5 font-bold uppercase text-primary">
                    {p.order_id}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-status-fresh-green/20 px-2 py-0.5 font-bold text-primary">
                    <span
                      aria-hidden="true"
                      className="inline-block size-2 rounded-full bg-status-fresh-green"
                    />
                    Accepted (demo)
                  </span>
                  <span>{dateTime(placedAt(p))}</span>
                </div>
                <h2 className="m-0 font-headline text-headline-sm text-primary wrap-anywhere">
                  {title}
                </h2>
                <div className="font-body text-body-sm text-on-surface-variant">
                  {p.snapshot.lines.length}{" "}
                  {p.snapshot.lines.length === 1 ? "item" : "items"} ·{" "}
                  {p.request.destination}
                </div>
              </div>
              <div className="flex items-center justify-between gap-space-md lg:justify-end">
                <div className="lg:text-right">
                  <div className="font-headline text-headline-md font-bold text-primary">
                    <span>{currency(p.snapshot.gross_total)}</span>{" "}
                    <span className="font-label text-label-sm font-normal text-secondary">
                      incl. VAT
                    </span>
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
                <PurchaseSheet p={p} />
                <div className="font-label text-label-sm text-secondary">
                  Delivery to {p.request.destination} on{" "}
                  {p.request.delivery_date} · Accepted by demo order service
                </div>
              </div>
            )}
          </article>
        );
      })}
    </>
  );
}
