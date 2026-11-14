import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../../shared/api/client";
import type { OrderListItem, Proposal } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { currency, dateTime } from "../../../shared/lib/format";
import { useAuth } from "../../auth/useAuth";
import { formatDate } from "../../schedules/model/scheduleStatus";
import { getPurchase } from "../api/purchasesApi";
import { cancelReasonText } from "../model/orders";
import { PurchaseSheet } from "./PurchaseSheet";

const secondaryButton =
  "cursor-pointer rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50";
const linkButton =
  "inline-flex items-center gap-1 rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary no-underline hover:bg-surface-container-high";
const titleLink =
  "text-primary underline decoration-outline-variant underline-offset-4 hover:decoration-primary";

export function OrderRow({
  item,
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
      className="purchase-row min-w-0 scroll-mt-space-lg rounded-xl bg-surface-pure p-space-md shadow-level-2 md:p-space-lg"
    >
      <div className="flex flex-col justify-between gap-space-md lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
          <div className="flex flex-wrap items-center gap-space-sm font-label text-label-sm text-secondary">
            <Badge value={item.status} />
            {item.status === "scheduled" && item.paused && (
              <Badge value="paused" />
            )}
            {item.status === "scheduled" && item.scheduled_for && (
              <span className="font-bold text-primary">
                Runs {formatDate(item.scheduled_for)}
              </span>
            )}
            {item.order_id && (
              <span className="order-reference rounded bg-surface-container-high px-2 py-0.5 font-bold uppercase text-primary">
                {item.order_id}
              </span>
            )}
            <span>
              {item.status === "placed" && item.placed_at
                ? `Placed ${dateTime(item.placed_at)}`
                : `Updated ${dateTime(item.updated_at)}`}
            </span>
          </div>
          <h2 className="m-0 font-headline text-headline-sm text-primary wrap-anywhere">
            {titleTarget ? (
              <Link to={titleTarget} className={titleLink}>
                {title}
              </Link>
            ) : (
              title
            )}
          </h2>
          <div className="font-body text-body-sm text-on-surface-variant">
            {item.line_count} {item.line_count === 1 ? "line" : "lines"}
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
          {item.status === "cancelled" && (
            <p className="m-0 font-body text-body-sm text-on-surface-variant">
              {cancelReasonText(item.cancel_reason)}
            </p>
          )}
          {notice && (
            <p
              role="alert"
              className="m-0 rounded-lg bg-error-container px-space-md py-space-xs font-body text-body-sm text-on-error-container"
            >
              {notice}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-space-sm lg:items-end">
          <div className="flex items-center justify-between gap-space-md lg:justify-end">
            <div className="font-headline text-headline-md font-bold text-primary lg:text-right">
              {currency(item.gross_total, item.currency ?? "EUR")}{" "}
              <span className="font-label text-label-sm font-normal text-secondary">
                incl. VAT
              </span>
            </div>
            {canExpand && proposalId && (
              <button
                type="button"
                aria-label={`Order details: ${title}`}
                aria-expanded={expanded}
                aria-controls={`details-${proposalId}`}
                onClick={() => onToggle(proposalId)}
                className="cursor-pointer rounded-lg border-0 bg-surface-container-low p-3 text-primary hover:bg-surface-container-high"
              >
                <Icon name={expanded ? "expand_less" : "expand_more"} />
              </button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-space-sm">
            {item.status === "placed" && item.order_id && (
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
          </div>
        </div>
      </div>
      {canExpand && proposalId && expanded && (
        <PlacedDetails proposalId={proposalId} known={known} />
      )}
    </article>
  );
}

function PlacedDetails({
  proposalId,
  known,
}: {
  proposalId: string;
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
      <div className="font-label text-label-md uppercase tracking-wider text-secondary">
        Ordered items
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
