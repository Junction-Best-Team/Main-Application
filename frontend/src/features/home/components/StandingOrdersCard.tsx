import { Link } from "react-router-dom";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { currency } from "../../../shared/lib/format";
import {
  cadenceLabel,
  formatDate,
  scheduleChip,
  type ChipTone,
} from "../../schedules/model/scheduleStatus";
import { useStandingOrders } from "../hooks/useStandingOrders";

const toneClass: Record<ChipTone, string> = {
  positive: "bg-status-fresh-green/30 text-primary",
  attention: "bg-amber-100 text-amber-900",
  neutral: "bg-surface-container-highest text-primary",
  negative: "bg-error-container text-on-error-container",
};
const rowClass =
  "group flex items-center justify-between gap-space-sm rounded-lg bg-surface-container-low p-space-sm no-underline hover:bg-surface-container";

export function StandingOrdersCard() {
  const { schedules, loading, error } = useStandingOrders(3);
  return (
    <section
      aria-labelledby="home-schedule"
      className="flex min-w-0 flex-col gap-space-sm rounded-xl bg-surface-pure p-space-lg shadow-level-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-space-sm">
        <h3
          id="home-schedule"
          className="m-0 flex items-center gap-space-xs font-headline text-headline-sm text-primary"
        >
          <Icon name="calendar_clock" className="text-wholesale-teal" />
          Standing orders
        </h3>
        <Link
          to="/schedules"
          className="inline-flex items-center gap-1 font-label text-label-md text-wholesale-teal no-underline hover:text-deep-ocean-navy"
        >
          View all standing orders
          <Icon name="arrow_forward" className="text-[16px]" />
        </Link>
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-lg bg-error-container p-space-md text-on-error-container"
        >
          {error}
        </div>
      )}
      {loading && !error && (
        <p role="status" className="m-0 text-secondary">
          Loading standing orders…
        </p>
      )}
      {!loading && !error && schedules.length === 0 && (
        <p className="m-0 text-secondary">
          No standing orders yet.{" "}
          <Link to="/purchases" className="text-wholesale-teal">
            Schedule a past order
          </Link>{" "}
          to repeat it on a cadence.
        </p>
      )}
      <ul className="m-0 flex list-none flex-col gap-space-xs p-0">
        {schedules.map((s) => {
          const chip = scheduleChip(s);
          return (
            <li key={s.id}>
              <Link to={`/schedules/${s.id}`} className={rowClass}>
                <span className="flex min-w-0 items-start gap-space-sm">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary-container text-on-secondary-container">
                    <Icon name="event_repeat" className="text-[20px]" />
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate font-label text-label-lg text-deep-ocean-navy">
                      {s.title}
                    </span>
                    <span className="font-label text-label-sm text-secondary">
                      {cadenceLabel(s.recurrence)} •{" "}
                      <span className="font-semibold text-on-surface">
                        {s.next_run_date
                          ? `Next: ${formatDate(s.next_run_date)}`
                          : "No upcoming run"}
                      </span>
                    </span>
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  <span
                    className={`rounded px-2 py-0.5 text-right font-label text-label-sm font-semibold ${toneClass[chip.tone]}`}
                  >
                    {chip.label}
                  </span>
                  <span className="font-label text-label-md font-bold text-deep-ocean-navy">
                    {currency(s.agreed_gross_total, s.currency)}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
