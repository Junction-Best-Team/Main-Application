import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { useDebounced } from "../../../shared/hooks/useDebounced";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useOrders } from "../hooks/useOrders";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { isAccepted } from "../model/acceptedOrders";
import { placedItemFromProposal } from "../model/orders";
import {
  DEFAULT_PAST_ORDER_FILTERS,
  filterAndSortPastOrders,
  orderApiFilters,
  PAST_ORDER_PERIODS,
  PAST_ORDER_SORTS,
  PAST_ORDER_STATUSES,
  type PastOrderFilters,
  type PastOrderPeriod,
  type PastOrderSort,
  type PastOrderStatus,
} from "../model/pastOrderFilters";
import { OrdersList } from "../components/OrdersList";
import { PurchaseReview } from "../components/PurchaseReview";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";

const filterSelectClass =
  "rounded-lg border-0 bg-surface-pure px-space-md py-3 font-label text-label-md text-on-surface shadow-level-2";

export function PurchasesPage() {
  const { proposalId } = useParams();
  const [filters, setFilters] = useState<PastOrderFilters>(
    DEFAULT_PAST_ORDER_FILTERS,
  );
  // Search and status are asked of the server; the typed text is sent once typing pauses.
  const asked = orderApiFilters({
    ...filters,
    query: useDebounced(filters.query),
  });
  const {
    items: fetched,
    loading,
    error,
    nextOffset,
    showMore,
    cancel,
    cancelling,
    notices,
    dismissNotice,
  } = useOrders(asked);
  const detail = usePurchaseDetail({ proposalId });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const scrolled = useRef<string | null>(null);
  const placedTarget = detail.p && isAccepted(detail.p) ? detail.p : null;
  // A deep link to a placed order older than the loaded pages still shows its row.
  const orders = useMemo(
    () =>
      placedTarget &&
      !fetched.some(
        (o) =>
          o.status === "placed" && o.proposal_id === placedTarget.proposal_id,
      )
        ? [placedItemFromProposal(placedTarget), ...fetched]
        : fetched,
    [placedTarget, fetched],
  );
  // Period and sort run over the loaded rows; the row a deep link points at is never hidden.
  const shown = useMemo(
    () => filterAndSortPastOrders(orders, filters, Date.now(), proposalId),
    [orders, filters, proposalId],
  );
  // Keep loading pages while the filters leave the visible list sparse.
  useEffect(() => {
    if (loading || nextOffset === null || shown.length >= 5) return;
    void showMore();
  }, [loading, nextOffset, shown.length, showMore, filters]);
  // A cancellation notice belongs on its row; when the row is gone it is shown above the list.
  const strayNotices = Object.entries(notices).filter(
    ([id]) => !orders.some((o) => o.proposal_id === id),
  );
  const targetAccepted = Boolean(placedTarget);
  useEffect(() => {
    if (proposalId && targetAccepted)
      setExpanded((prev) => new Set([...prev, proposalId]));
  }, [proposalId, targetAccepted]);
  useEffect(() => {
    if (!proposalId || !targetAccepted || scrolled.current === proposalId)
      return;
    const target = document.getElementById(`order-${proposalId}`);
    if (target) {
      target.scrollIntoView({ block: "center" });
      scrolled.current = proposalId;
    }
  }, [proposalId, targetAccepted, expanded]);
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  if (proposalId && !detail.p)
    return (
      <main className="p-space-lg">
        <ErrorMessage message={detail.error} debug={detail.errorDebug} />
        {!detail.error && <p role="status">Loading purchase…</p>}
      </main>
    );
  if (detail.p && !isAccepted(detail.p))
    return (
      <PurchaseReview
        flow={detail}
        notice="This purchase hasn't been placed yet — review and confirm the exact basket below, or return to its request."
      />
    );
  const m = MOCK.pastOrders;
  const hasFilter = filters.query.trim() !== "" || filters.status !== "all";
  return (
    <main>
      <section className="border-b border-border-subtle bg-surface-pure px-margin-sm py-space-lg md:px-margin">
        <div className="mx-auto flex max-w-6xl flex-col justify-between gap-space-md sm:flex-row sm:items-center">
          <h1 className="m-0 font-headline text-headline-md tracking-normal text-primary md:text-headline-lg-mobile">
            Past Orders
          </h1>
        </div>
      </section>

      <section className="px-margin-sm py-space-lg md:px-margin">
        <div className="mx-auto flex max-w-6xl flex-col gap-space-md lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Icon
              name="search"
              className="absolute left-space-md top-1/2 -translate-y-1/2 text-secondary"
            />
            <input
              type="search"
              value={filters.query}
              onChange={(e) =>
                setFilters((prev) => ({ ...prev, query: e.target.value }))
              }
              aria-label={m.searchLabel}
              placeholder={m.searchPlaceholder}
              className="w-full rounded-lg border-0 bg-surface-pure py-3 pl-11 pr-space-md font-body text-body-md text-on-surface shadow-level-2"
            />
          </div>
          <div className="flex flex-wrap items-center gap-space-sm">
            <label className="sr-only" htmlFor="past-orders-period">
              Period
            </label>
            <select
              id="past-orders-period"
              value={filters.period}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  period: e.target.value as PastOrderPeriod,
                }))
              }
              className={filterSelectClass}
            >
              {PAST_ORDER_PERIODS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="past-orders-sort">
              Sort
            </label>
            <select
              id="past-orders-sort"
              value={filters.sort}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  sort: e.target.value as PastOrderSort,
                }))
              }
              className={filterSelectClass}
            >
              {PAST_ORDER_SORTS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="past-orders-status">
              Status
            </label>
            <select
              id="past-orders-status"
              value={filters.status}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  status: e.target.value as PastOrderStatus,
                }))
              }
              className={filterSelectClass}
            >
              {PAST_ORDER_STATUSES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <section className="px-margin-sm pb-space-xl md:px-margin">
        <div className="mx-auto flex max-w-6xl flex-col gap-space-md">
          {error && (
            <div
              role="alert"
              className="rounded-lg bg-error-container p-space-md text-on-error-container"
            >
              {error}
            </div>
          )}
          {strayNotices.map(([id, message]) => (
            <div
              key={id}
              role="alert"
              className="flex items-center justify-between gap-space-md rounded-lg bg-error-container p-space-md text-on-error-container"
            >
              <span>{message}</span>
              <button
                type="button"
                onClick={() => dismissNotice(id)}
                className="cursor-pointer border-0 bg-transparent font-label text-label-md text-on-error-container underline"
              >
                Dismiss
              </button>
            </div>
          ))}
          <OrdersList
            items={shown}
            loading={loading && shown.length === 0}
            expanded={expanded}
            toggle={toggle}
            known={placedTarget}
            cancelling={cancelling}
            notices={notices}
            onCancel={cancel}
          />
          {loading && shown.length > 0 && (
            <p
              role="status"
              className="m-0 py-space-lg text-center text-secondary"
            >
              Loading orders…
            </p>
          )}
          {!loading && !error && orders.length === 0 && !hasFilter && (
            <section className="rounded-xl bg-surface-pure p-space-xl text-center">
              <h2 className="m-0 font-headline text-headline-sm text-primary">
                No orders yet
              </h2>
              <p className="text-secondary">
                Orders you request, place or schedule will appear here.
              </p>
            </section>
          )}
          {!loading &&
            !error &&
            shown.length === 0 &&
            (orders.length > 0 || hasFilter) && (
              <section className="rounded-xl bg-surface-pure p-space-xl text-center">
                <h2 className="m-0 font-headline text-headline-sm text-primary">
                  No matching past orders
                </h2>
                <p className="text-secondary">
                  Try a different search, period, or status filter.
                </p>
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
