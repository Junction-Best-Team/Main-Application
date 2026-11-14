import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useAuth } from "../../auth/useAuth";
import { useAcceptedOrders } from "../hooks/useAcceptedOrders";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { isAccepted } from "../model/acceptedOrders";
import {
  DEFAULT_PAST_ORDER_FILTERS,
  filterAndSortPastOrders,
  PAST_ORDER_PERIODS,
  PAST_ORDER_SORTS,
  PAST_ORDER_STATUSES,
  type PastOrderFilters,
  type PastOrderPeriod,
  type PastOrderSort,
  type PastOrderStatus,
} from "../model/pastOrderFilters";
import { PurchaseList } from "../components/PurchaseList";
import { PurchaseReview } from "../components/PurchaseReview";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";

const filterSelectClass =
  "rounded-lg border-0 bg-surface-pure px-space-md py-3 font-label text-label-md text-on-surface shadow-level-2";

export function PurchasesPage() {
  const { proposalId } = useParams();
  const { session } = useAuth();
  const {
    orders: fetched,
    loading,
    error,
    nextOffset,
    refresh,
    showMore,
  } = useAcceptedOrders();
  const detail = usePurchaseDetail({ proposalId });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<PastOrderFilters>(
    DEFAULT_PAST_ORDER_FILTERS,
  );
  const scrolled = useRef<string | null>(null);
  const orders = useMemo(
    () =>
      detail.p &&
      isAccepted(detail.p) &&
      !fetched.some((p) => p.proposal_id === detail.p?.proposal_id)
        ? [detail.p, ...fetched]
        : fetched,
    [detail.p, fetched],
  );
  const visible = useMemo(
    () => filterAndSortPastOrders(orders, filters),
    [orders, filters],
  );
  const targetAccepted = detail.p && isAccepted(detail.p);
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
  // Keep loading accepted pages while filters leave the visible list sparse.
  useEffect(() => {
    if (loading || nextOffset === null || visible.length >= 5) return;
    void showMore();
  }, [loading, nextOffset, visible.length, showMore, filters]);
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  if (proposalId && !detail.p)
    return (
      <main className="p-space-lg">
        <ErrorMessage message={detail.error} />
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
  const emptyLoaded = !loading && !error && orders.length === 0;
  const emptyFiltered =
    !loading && !error && orders.length > 0 && visible.length === 0;
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
              <div className="font-label text-label-sm uppercase text-secondary">
                {m.account.label}
              </div>
              <div className="font-label text-label-md text-primary">
                {session?.buyer_id}
              </div>
            </div>
          </div>
          <button
            className="self-start text-label-md"
            onClick={refresh}
            disabled={loading}
          >
            Refresh purchases
          </button>
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
          <PurchaseList orders={visible} expanded={expanded} toggle={toggle} />
          {loading && (
            <p
              role="status"
              className="m-0 py-space-lg text-center text-secondary"
            >
              Loading past orders…
            </p>
          )}
          {emptyLoaded && (
            <section className="rounded-xl bg-surface-pure p-space-xl text-center">
              <h2 className="m-0 font-headline text-headline-sm text-primary">
                No past orders yet
              </h2>
              <p className="text-secondary">
                Orders you approve in a request will appear here.
              </p>
            </section>
          )}
          {emptyFiltered && (
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
