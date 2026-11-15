import { KitchenPattern } from "../../../shared/components/KitchenPattern";
import { motion } from "motion/react";
import { SkeletonLine } from "../../../shared/components/SkeletonSwap";
import { Link, useParams } from "react-router-dom";
import type { ScheduleDetail } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { currency } from "../../../shared/lib/format";
import { useAuth } from "../../auth/useAuth";
import { RunHistory } from "../components/RunHistory";
import { ScheduleActions } from "../components/ScheduleActions";
import { ScheduleChip } from "../components/ScheduleChip";
import { ScheduleLines } from "../components/ScheduleLines";
import { useSchedule } from "../hooks/useSchedule";
import {
  cadenceLabel,
  formatDate,
  needsNewOrderToRestart,
  stopReasonText,
} from "../model/scheduleStatus";

const card = "rounded-xl bg-surface-pure p-space-lg shadow-level-2";
const heading = "m-0 mb-space-md font-headline text-headline-sm text-primary";
const linkClass =
  "inline-flex items-center gap-1 font-label text-label-md text-wholesale-teal no-underline hover:underline";

function Term({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="font-label text-label-sm uppercase text-secondary">
        {label}
      </dt>
      <dd className="m-0 text-body-md text-on-surface">{value}</dd>
    </div>
  );
}

function StopNotice({ s }: { s: ScheduleDetail }) {
  const { session } = useAuth();
  const canWrite = !session?.role || session.role === "approver";
  const newOrder = needsNewOrderToRestart(s.stop_reason);
  return (
    <div
      role="note"
      className="flex flex-col gap-space-sm rounded-xl bg-amber-100 p-space-lg text-amber-900 dark:bg-amber-900/40 dark:text-amber-100"
    >
      <p className="m-0 font-label text-label-lg">
        This standing order stopped and needs your attention.
      </p>
      <p className="m-0 text-body-md">{stopReasonText(s.stop_reason)}</p>
      <div className="flex flex-wrap items-center gap-space-md">
        {canWrite && (
          <Link
            to={`/schedules/${s.id}/edit?restart=1`}
            className="inline-flex items-center justify-center rounded-lg bg-primary-container px-space-lg py-3 font-label text-label-lg text-on-primary no-underline hover:bg-primary"
          >
            {newOrder ? "Restart from a new order" : "Restart"}
          </Link>
        )}
        {s.conversation_id && (
          <Link
            to={`/conversations/${s.conversation_id}`}
            className={linkClass}
          >
            Open the conversation
          </Link>
        )}
      </div>
    </div>
  );
}

export function ScheduleDetailPage() {
  const { scheduleId } = useParams();
  const {
    schedule: s,
    loading,
    olderLoading,
    error,
    reload,
    showOlderRuns,
    apply,
  } = useSchedule(scheduleId);

  if (!s && loading && !error) return <ScheduleDetailSkeleton />;
  if (!s)
    return (
      <main className="isolate mx-auto flex w-full max-w-6xl flex-col gap-space-md px-margin-sm py-space-lg md:px-margin">
        <KitchenPattern seed={4} />
        <Link to="/schedules" className={linkClass}>
          <Icon name="arrow_back" className="text-[16px]" />
          All standing orders
        </Link>
        <ErrorMessage message={error} />
      </main>
    );

  const eur = s.currency ?? "EUR";
  return (
    <motion.main
      className="isolate"
      // Fades in over the skeleton's place once the standing order has loaded.
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      <KitchenPattern seed={4} />
      <section className="border-b border-border-subtle bg-surface-pure px-margin-sm py-space-lg md:px-margin md:py-space-xl">
        <div className="mx-auto flex max-w-6xl flex-col gap-space-md">
          <Link to="/schedules" className={linkClass}>
            <Icon name="arrow_back" className="text-[16px]" />
            All standing orders
          </Link>
          <div className="flex flex-col justify-between gap-space-md md:flex-row md:items-start">
            <div className="flex min-w-0 flex-col gap-space-xs">
              <h1 className="m-0 font-headline text-headline-lg-mobile tracking-normal text-primary wrap-anywhere md:text-headline-lg">
                {s.title}
              </h1>
              <div className="flex flex-wrap items-center gap-space-sm">
                <ScheduleChip schedule={s} />
                <span className="text-body-md text-on-surface-variant">
                  {cadenceLabel(s.recurrence)}
                </span>
              </div>
            </div>
            <ScheduleActions schedule={s} onChanged={apply} onStale={reload} />
          </div>
        </div>
      </section>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-space-lg px-margin-sm py-space-lg md:px-margin">
        <ErrorMessage message={error} />
        {s.status === "stopped" && <StopNotice s={s} />}

        <div className="grid grid-cols-1 gap-space-lg lg:grid-cols-2">
          <section aria-labelledby="schedule-terms" className={card}>
            <h2 id="schedule-terms" className={heading}>
              Terms
            </h2>
            <dl className="m-0 grid grid-cols-1 gap-space-md sm:grid-cols-2">
              <Term label="Repeats" value={cadenceLabel(s.recurrence)} />
              <Term label="First run" value={formatDate(s.first_run_date)} />
              <Term
                label="Next run"
                value={
                  s.status === "paused"
                    ? "Paused until resumed"
                    : s.next_run_date
                      ? formatDate(s.next_run_date)
                      : "No further runs"
                }
              />
              <Term label="Valid until" value={formatDate(s.valid_until)} />
              <Term
                label="Delivery"
                value={`${s.delivery_offset_days} ${s.delivery_offset_days === 1 ? "day" : "days"} after each run`}
              />
              <Term
                label="Agreed total"
                value={`${currency(s.agreed_gross_total, eur)} incl. tax`}
              />
              <Term
                label="Price ceiling"
                value={
                  s.price_ceiling_gross
                    ? currency(s.price_ceiling_gross, eur)
                    : "None"
                }
              />
            </dl>
          </section>

          <section aria-labelledby="schedule-lines" className={card}>
            <h2 id="schedule-lines" className={heading}>
              Agreed lines
            </h2>
            <ScheduleLines lines={s.lines ?? []} currencyCode={s.currency} />
          </section>
        </div>

        <section aria-labelledby="schedule-runs" className={card}>
          <h2 id="schedule-runs" className={heading}>
            Run history
          </h2>
          <RunHistory
            runs={s.runs}
            currencyCode={s.currency}
            hasMore={s.runs_next_offset != null}
            loadingMore={olderLoading}
            onShowOlder={() => void showOlderRuns()}
          />
        </section>
      </div>
    </motion.main>
  );
}

/** The details page's layout with placeholder lines while the standing order loads. */
function ScheduleDetailSkeleton() {
  return (
    <main className="isolate">
      <KitchenPattern seed={4} />
      <p role="status" className="sr-only">
        Loading standing order…
      </p>
      <section
        aria-hidden="true"
        className="border-b border-border-subtle bg-surface-pure px-margin-sm py-space-lg md:px-margin md:py-space-xl"
      >
        <div className="mx-auto flex max-w-6xl flex-col gap-space-md">
          <Link to="/schedules" className={linkClass}>
            <Icon name="arrow_back" className="text-[16px]" />
            All standing orders
          </Link>
          <div className="flex flex-col justify-between gap-space-md md:flex-row md:items-start">
            <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
              <SkeletonLine height="h-8 md:h-11" bar="h-7" width="w-1/2" />
              <div className="flex items-center gap-space-sm">
                <SkeletonLine
                  height="h-[26px]"
                  bar="h-[26px] rounded-full"
                  width="w-20"
                />
                <SkeletonLine height="h-6" width="w-32" />
              </div>
            </div>
            <div className="flex gap-space-sm">
              <SkeletonLine height="h-[34px]" bar="h-[34px]" width="w-20" />
              <SkeletonLine height="h-[34px]" bar="h-[34px]" width="w-20" />
            </div>
          </div>
        </div>
      </section>
      <div
        aria-hidden="true"
        className="mx-auto flex w-full max-w-6xl flex-col gap-space-lg px-margin-sm py-space-lg md:px-margin"
      >
        <div className="grid grid-cols-1 gap-space-lg lg:grid-cols-2">
          <section className={card}>
            <SkeletonLine
              height="h-7"
              bar="h-5"
              width="w-24"
              className="mb-space-md"
            />
            <div className="grid grid-cols-1 gap-space-md sm:grid-cols-2">
              {Array.from({ length: 7 }, (_, n) => (
                <div key={n} className="flex flex-col gap-0.5">
                  <SkeletonLine height="h-3.5" bar="h-2.5" width="w-16" />
                  <SkeletonLine
                    height="h-6"
                    width={n % 2 ? "w-1/2" : "w-2/3"}
                  />
                </div>
              ))}
            </div>
          </section>
          <section className={card}>
            <SkeletonLine
              height="h-7"
              bar="h-5"
              width="w-32"
              className="mb-space-md"
            />
            <div className="flex flex-col gap-space-sm">
              {[0, 1, 2].map((n) => (
                <SkeletonLine key={n} height="h-12" bar="h-10" />
              ))}
            </div>
          </section>
        </div>
        <section className={card}>
          <SkeletonLine
            height="h-7"
            bar="h-5"
            width="w-28"
            className="mb-space-md"
          />
          <div className="flex flex-col gap-space-sm">
            {[0, 1].map((n) => (
              <SkeletonLine key={n} height="h-16" bar="h-14" />
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
