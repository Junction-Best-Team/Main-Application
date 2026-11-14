import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Icon,
  InertButton,
  InertInput,
} from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useAuth } from "../../auth/useAuth";
import { useOrders } from "../hooks/useOrders";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { isAccepted } from "../model/acceptedOrders";
import {
  ORDER_FILTERS,
  placedItemFromProposal,
  type OrderFilter,
} from "../model/orders";
import { OrdersList } from "../components/OrdersList";
import { PurchaseReview } from "../components/PurchaseReview";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
export function PurchasesPage() {
  const { proposalId } = useParams();
  const { session } = useAuth();
  const {
    items: fetched,
    loading,
    error,
    nextOffset,
    refresh,
    showMore,
    cancel,
    cancelling,
    notices,
    dismissNotice,
  } = useOrders();
  const detail = usePurchaseDetail({ proposalId });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<OrderFilter>("all");
  const scrolled = useRef<string | null>(null);
  const placedTarget = detail.p && isAccepted(detail.p) ? detail.p : null;
  // A deep link to a placed order older than the loaded pages still shows its row.
  const orders =
    placedTarget &&
    !fetched.some(
      (o) =>
        o.status === "placed" && o.proposal_id === placedTarget.proposal_id,
    )
      ? [placedItemFromProposal(placedTarget), ...fetched]
      : fetched;
  const shown =
    filter === "all" ? orders : orders.filter((o) => o.status === filter);
  const filterLabel = ORDER_FILTERS.find((f) => f.value === filter)?.label;
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
            <InertInput
              label={m.searchLabel}
              placeholder={m.searchPlaceholder}
              className="w-full rounded-lg border-0 bg-surface-pure py-3 pl-11 pr-space-md font-body text-body-md text-on-surface shadow-level-2"
            />
          </div>
          <div className="flex flex-wrap items-center gap-space-sm">
            {[m.periodLabel, m.sortLabel].map((label) => (
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
        <div
          role="group"
          aria-label="Filter orders by status"
          className="mx-auto mt-space-md flex max-w-6xl flex-wrap gap-space-sm"
        >
          {ORDER_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={`cursor-pointer rounded-full border px-space-md py-2 font-label text-label-md ${
                filter === f.value
                  ? "border-primary bg-primary text-on-primary"
                  : "border-outline-variant bg-surface-pure text-primary hover:bg-surface-container-high"
              }`}
            >
              {f.label}
            </button>
          ))}
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
            expanded={expanded}
            toggle={toggle}
            known={placedTarget}
            cancelling={cancelling}
            notices={notices}
            onCancel={cancel}
          />
          {loading && (
            <p
              role="status"
              className="m-0 py-space-lg text-center text-secondary"
            >
              Loading orders…
            </p>
          )}
          {!loading && !error && orders.length === 0 && (
            <section className="rounded-xl bg-surface-pure p-space-xl text-center">
              <h2 className="m-0 font-headline text-headline-sm text-primary">
                No orders yet
              </h2>
              <p className="text-secondary">
                Orders you request, place or schedule will appear here.
              </p>
            </section>
          )}
          {!loading && orders.length > 0 && shown.length === 0 && (
            <p className="m-0 py-space-lg text-center text-secondary">
              No {filterLabel?.toLowerCase()} orders loaded
              {nextOffset !== null
                ? " yet. Show more orders to look further."
                : "."}
            </p>
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
