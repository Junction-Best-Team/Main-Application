import { KitchenPattern } from "../../../shared/components/KitchenPattern";
import { Link } from "react-router-dom";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { ScheduleCard } from "../components/ScheduleCard";
import { useSchedules } from "../hooks/useSchedules";
import { isSuperseded } from "../model/scheduleStatus";
import {
  SkeletonLine,
  SkeletonList,
} from "../../../shared/components/SkeletonSwap";

const primaryLink =
  "inline-flex items-center justify-center gap-space-xs self-start rounded-lg bg-primary-container px-space-lg py-3 font-label text-label-lg text-on-primary no-underline hover:bg-primary";

/** ScheduleCard's fixed layout: a 28px title row with the 26px status pill, four 24px facts
 *  in two columns, the 20px status line and the 34px action row (min-h-52 overall). */
function ScheduleCardSkeleton() {
  return (
    <div className="flex min-h-52 flex-col gap-space-sm rounded-xl bg-surface-pure p-space-lg shadow-level-2">
      <div className="flex h-7 items-center justify-between gap-space-sm">
        <SkeletonLine height="h-7" bar="h-5" width="w-1/2" />
        <SkeletonLine
          height="h-[26px]"
          bar="h-[26px] rounded-full"
          width="w-20"
        />
      </div>
      <div className="grid grid-cols-2 gap-x-space-lg gap-y-space-xs">
        <SkeletonLine height="h-6" width="w-3/4" />
        <SkeletonLine height="h-6" width="w-2/3" />
        <SkeletonLine height="h-6" width="w-1/2" />
        <SkeletonLine height="h-6" width="w-1/3" />
      </div>
      <SkeletonLine height="h-5" bar="h-3" width="w-2/5" />
      <div className="mt-auto flex h-[34px] items-center gap-x-space-lg">
        <SkeletonLine height="h-[34px]" bar="h-4" width="w-24" />
        <SkeletonLine height="h-[34px]" bar="h-[34px]" width="w-20" />
      </div>
    </div>
  );
}

export function SchedulesPage() {
  const { items, nextOffset, loading, error, refresh, showMore, replace } =
    useSchedules();
  // A restarted schedule has a successor in the list; do not show the old one twice.
  const visible = items.filter((s) => !isSuperseded(s));
  const empty = !loading && !error && visible.length === 0;
  return (
    <main className="isolate">
      <KitchenPattern seed={1} />
      <section className="border-b border-border-subtle bg-surface-pure px-margin-sm py-space-lg md:px-margin md:py-space-xl">
        <div className="mx-auto flex max-w-6xl flex-col justify-between gap-space-md md:flex-row md:items-end">
          <div className="flex flex-col gap-space-xs">
            <h1 className="m-0 font-headline text-headline-lg-mobile tracking-normal text-primary md:text-headline-lg">
              Standing orders
            </h1>
            <p className="m-0 max-w-2xl text-body-md text-on-surface-variant">
              Orders that repeat on a schedule at the terms you agreed.
            </p>
          </div>
          <Link to="/purchases" className={primaryLink}>
            <Icon name="event_repeat" className="text-[20px]" />
            Schedule an order
          </Link>
        </div>
      </section>

      <section className="px-margin-sm py-space-lg md:px-margin">
        <div className="mx-auto flex max-w-6xl flex-col gap-space-md">
          <ErrorMessage message={error} />
          <SkeletonList
            loading={loading && visible.length === 0}
            items={visible}
            count={4}
            label="Loading standing orders…"
            className="grid grid-cols-1 gap-space-md lg:grid-cols-2"
            itemKey={(s) => s.id}
            renderSkeleton={() => <ScheduleCardSkeleton />}
            renderItem={(s) => (
              <ScheduleCard
                schedule={s}
                onChanged={replace}
                onStale={() => refresh(true)}
              />
            )}
          />
          {error && visible.length === 0 && !loading && (
            <button
              type="button"
              onClick={() => void refresh()}
              className="cursor-pointer self-start rounded-lg border border-outline-variant bg-surface-pure px-space-lg py-3 font-label text-label-md text-primary hover:bg-surface-container-high"
            >
              Try again
            </button>
          )}
          {empty && (
            <section className="flex flex-col items-center gap-space-sm rounded-xl bg-surface-pure p-space-xl text-center shadow-level-2">
              <h2 className="m-0 font-headline text-headline-sm text-primary">
                No standing orders yet
              </h2>
              <p className="m-0 max-w-md text-secondary">
                Pick an order you have placed and schedule it to repeat. You
                approve the terms once and later runs follow them.
              </p>
              <Link to="/purchases" className={primaryLink}>
                Schedule an order
              </Link>
            </section>
          )}
          {nextOffset !== null && (
            <button
              type="button"
              onClick={() => void showMore()}
              disabled={loading}
              className="cursor-pointer self-center rounded-lg border border-outline-variant bg-surface-pure px-space-lg py-3 font-label text-label-md text-primary hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
            >
              Show more
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
