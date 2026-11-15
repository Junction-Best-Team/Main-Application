import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../../shared/api/client";
import type { OrderListItem, Proposal } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { dateTime } from "../../../shared/lib/format";
import { useAuth } from "../../auth/useAuth";
import { formatDate } from "../../schedules/model/scheduleStatus";
import { getPurchase } from "../api/purchasesApi";
import { cancelReasonText, deliveryDay } from "../model/orders";
import { OrderStatus } from "./OrderStatus";
import { OrderRowDecor } from "./OrderRowDecor";
import { RollingPrice } from "../../../shared/components/RollingPrice";
import { PurchaseSheet } from "./PurchaseSheet";

const secondaryButton =
  "cursor-pointer rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50";
const linkButton =
  "inline-flex items-center gap-1 rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary no-underline hover:bg-surface-container-high";
const titleLink =
  "text-primary underline decoration-outline-variant underline-offset-4 hover:decoration-primary";

export function OrderRow({
  item,
  decorVariant = 0,
  expanded,
  onToggle,
  known,
  cancelling,
  notice,
  onCancel,
}: {
  item: OrderListItem;
  expanded: boolean;
  onToggle: (proposalId: string) => void;
  /** The proposal when the page already loaded it (a deep link), so the row does not refetch. */
  known?: Proposal;
  cancelling: boolean;
  notice?: string;
  onCancel: (proposalId: string) => Promise<void>;
  /** Which background pattern fills the row's empty middle (exploration). */
  decorVariant?: number;
}) {
  const [confirming, setConfirming] = useState(false);
  const title = item.title || "Order";
  const proposalId = item.proposal_id;
  const canExpand = item.status === "placed" && Boolean(proposalId);
  const titleTarget =
    item.status === "scheduled" && item.schedule_id
      ? `/schedules/${item.schedule_id}`
      : item.status === "pending" && proposalId
        ? `/purchases/${proposalId}`
        : null;
  return (
    <article
      id={canExpand ? `order-${proposalId}` : undefined}
      className="purchase-row min-w-0 scroll-mt-space-lg overflow-hidden rounded-xl bg-surface-pure p-space-md shadow-level-2 md:p-space-lg"
    >
      <div className="relative isolate flex flex-col justify-between gap-space-md lg:flex-row lg:items-center">
        {/* Faint pattern in the row's empty space (exploration, see OrderRowDecor). */}
        <OrderRowDecor variant={decorVariant} expanded={expanded} />
        {/* On desktop the left side only takes the width its content needs. */}
        <div className="flex min-w-0 flex-1 flex-col gap-space-xs lg:flex-initial">
          <div
            data-decor="meta"
            className="flex h-[26px] items-center gap-space-sm overflow-hidden whitespace-nowrap font-label text-label-sm text-secondary"
          >
            <OrderStatus item={item} />
            {item.status === "scheduled" && item.paused && (
              <Badge value="paused" />
            )}
            {/* When it arrives (or runs), next to the progress. */}
            {item.status === "scheduled" && item.scheduled_for ? (
              <span className="font-bold text-primary">
                Runs {formatDate(item.scheduled_for)}
              </span>
            ) : (
              item.status === "placed" &&
              deliveryDay(item.fulfilment) && (
                <span className="font-bold text-primary">
                  {item.fulfilment?.status === "delivered"
                    ? "Delivered"
                    : "Delivery"}{" "}
                  {formatDate(deliveryDay(item.fulfilment))}
                </span>
              )
            )}
          </div>
          <h2
            data-decor="title"
            className="m-0 h-7 truncate font-headline text-headline-sm text-primary"
          >
            {titleTarget ? (
              <Link to={titleTarget} className={titleLink}>
                {title}
              </Link>
            ) : (
              title
            )}
          </h2>
          <div
            data-decor="lines"
            className="h-5 truncate font-body text-body-sm text-on-surface-variant"
          >
            {item.line_count} {item.line_count === 1 ? "line" : "lines"}
            {item.status === "cancelled" &&
              ` · ${cancelReasonText(item.cancel_reason)}`}
            {item.status !== "scheduled" &&
              item.schedule_id &&
              item.schedule_title && (
                <>
                  {" · "}
                  <Link
                    to={`/schedules/${item.schedule_id}`}
                    className="text-wholesale-teal"
                  >
                    From standing order {item.schedule_title}
                  </Link>
                </>
              )}
          </div>
          {notice && (
            <p
              role="alert"
              className="m-0 rounded-lg bg-error-container px-space-md py-space-xs font-body text-body-sm text-on-error-container"
            >
              {notice}
            </p>
          )}
        </div>
        {/* The empty middle (the pattern is drawn behind the whole row). */}
        <div className="hidden min-w-12 flex-1 lg:block" />
        <div
          data-decor="right"
          className="flex shrink-0 flex-col gap-space-xs lg:items-end"
        >
          {/* When it was placed or last changed: at the right end of the row. */}
          <div
            data-decor="when"
            className="flex h-[26px] items-center whitespace-nowrap font-label text-label-sm text-secondary"
          >
            {item.status === "placed" && item.placed_at
              ? `Placed ${dateTime(item.placed_at)}`
              : `Updated ${dateTime(item.updated_at)}`}
          </div>
          <div className="flex h-8 items-center justify-between gap-space-md lg:justify-end">
            <div
              data-decor="total"
              className="font-headline text-headline-md font-bold text-primary lg:text-right"
            >
              <RollingPrice
                value={item.gross_total}
                currencyCode={item.currency ?? "EUR"}
              />{" "}
              <span className="font-label text-label-sm font-normal text-secondary">
                incl. VAT
              </span>
            </div>
          </div>
          {/* Always reserved, so every row has the same height. */}
          <div
            data-decor="actions"
            className="flex min-h-[34px] flex-wrap items-center gap-space-sm"
          >
            {item.status === "placed" && item.order_id && !item.schedule_id && (
              <Link
                to={`/schedules/new?order=${encodeURIComponent(item.order_id)}`}
                className={linkButton}
              >
                <Icon name="event_repeat" className="text-[18px]" />
                Schedule this order
              </Link>
            )}
            {item.status === "pending" &&
              proposalId &&
              (confirming ? (
                <div
                  role="group"
                  aria-label="Confirm cancelling this request"
                  className="flex flex-wrap items-center gap-space-sm"
                >
                  <span className="font-label text-label-md text-primary">
                    Cancel this request?
                  </span>
                  <button
                    type="button"
                    disabled={cancelling}
                    onClick={async () => {
                      await onCancel(proposalId);
                      setConfirming(false);
                    }}
                    className="cursor-pointer rounded-lg border-0 bg-error px-space-md py-2 font-label text-label-md text-on-error disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Yes, cancel request
                  </button>
                  <button
                    type="button"
                    disabled={cancelling}
                    onClick={() => setConfirming(false)}
                    className={secondaryButton}
                  >
                    Keep request
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  className={secondaryButton}
                >
                  Cancel request
                </button>
              ))}
            {canExpand && proposalId && (
              <button
                type="button"
                aria-label={`Order details: ${title}`}
                aria-expanded={expanded}
                aria-controls={`details-${proposalId}`}
                onClick={() => onToggle(proposalId)}
                className="flex h-[34px] w-[34px] cursor-pointer items-center justify-center rounded-lg border border-outline-variant bg-surface-pure p-0 text-primary hover:bg-surface-container-high"
              >
                <Icon name={expanded ? "expand_less" : "expand_more"} />
              </button>
            )}
          </div>
        </div>
      </div>
      {canExpand && proposalId && expanded && (
        <PlacedDetails
          proposalId={proposalId}
          orderId={item.order_id}
          known={known}
        />
      )}
    </article>
  );
}

function PlacedDetails({
  proposalId,
  orderId,
  known,
}: {
  proposalId: string;
  orderId?: string | null;
  known?: Proposal;
}) {
  const { setSession } = useAuth();
  const [fetched, setFetched] = useState<Proposal | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (known) return;
    let active = true;
    getPurchase(proposalId)
      .then((p) => active && setFetched(p))
      .catch((e: unknown) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 401) setSession(null);
        else setError((e as Error).message);
      });
    return () => {
      active = false;
    };
  }, [proposalId, known, setSession]);
  const p = known ?? fetched;
  return (
    <div
      id={`details-${proposalId}`}
      className="mt-space-md flex flex-col gap-space-sm rounded-lg bg-surface-container-low p-space-md"
    >
      <div className="flex items-center justify-between gap-space-sm">
        <div className="font-label text-label-md uppercase tracking-wider text-secondary">
          Ordered items
        </div>
        {orderId && (
          <span className="order-reference rounded bg-surface-container-high px-2 py-0.5 font-label text-label-sm font-bold uppercase text-primary">
            Order {orderId}
          </span>
        )}
      </div>
      <ErrorMessage message={error} />
      {!p && !error && (
        <p role="status" className="m-0 text-secondary">
          Loading order details…
        </p>
      )}
      {p && (
        <>
          <PurchaseSheet p={p} />
          <div className="font-label text-label-sm text-secondary">
            Delivery to {p.request.destination} on {p.request.delivery_date} ·
            Accepted by demo order service
          </div>
        </>
      )}
    </div>
  );
}
