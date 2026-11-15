import { Link } from "react-router-dom";
import type { Schedule } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { currency } from "../../../shared/lib/format";
import {
  cadenceLabel,
  formatDate,
  RUN_STATUS_LABEL,
  stopReasonText,
} from "../model/scheduleStatus";
import { ScheduleActions } from "./ScheduleActions";
import { ScheduleChip } from "./ScheduleChip";

// Only the words underline on hover, never the arrow beside them.
const linkClass =
  "group inline-flex items-center gap-1 font-label text-label-md text-wholesale-teal no-underline hover:no-underline";

function nextRunText(s: Schedule) {
  if (s.status === "paused") return "Paused until resumed";
  return s.next_run_date
    ? `Next run ${formatDate(s.next_run_date)}`
    : "No further runs";
}

// One standing order in the list: terms at a glance, a link to the detail, and Pause/Resume.
export function ScheduleCard({
  schedule: s,
  onChanged,
  onStale,
}: {
  schedule: Schedule;
  onChanged: (next: Schedule) => void;
  onStale: () => Promise<void> | void;
}) {
  const lineCount = s.lines?.length ?? 0;
  return (
    <article
      aria-labelledby={`schedule-${s.id}`}
      // One fixed size for every card (and its skeleton): each part below has a set height.
      className="flex min-h-52 flex-col gap-space-sm rounded-xl bg-surface-pure p-space-lg shadow-level-2"
    >
      <div className="flex h-7 items-center justify-between gap-space-sm">
        <h2
          id={`schedule-${s.id}`}
          title={s.title}
          className="m-0 min-w-0 truncate font-headline text-headline-sm text-primary"
        >
          <Link to={`/schedules/${s.id}`} className="text-primary no-underline">
            {s.title}
          </Link>
        </h2>
        <div className="shrink-0">
          <ScheduleChip schedule={s} />
        </div>
      </div>
      <dl className="m-0 grid grid-cols-2 gap-x-space-lg gap-y-space-xs text-body-md text-on-surface-variant [&_dd]:min-w-0 [&_dd]:truncate [&>div]:h-6 [&>div]:min-w-0">
        <div className="flex items-center gap-space-xs">
          <Icon name="repeat" className="text-[18px] text-wholesale-teal" />
          <dt className="sr-only">Repeats</dt>
          <dd className="m-0">{cadenceLabel(s.recurrence)}</dd>
        </div>
        <div className="flex items-center gap-space-xs">
          <Icon name="event" className="text-[18px] text-wholesale-teal" />
          <dt className="sr-only">Next run</dt>
          <dd className="m-0">{nextRunText(s)}</dd>
        </div>
        <div className="flex items-center gap-space-xs">
          <Icon name="payments" className="text-[18px] text-wholesale-teal" />
          <dt className="sr-only">Agreed total</dt>
          <dd className="m-0">
            {currency(s.agreed_gross_total, s.currency ?? "EUR")} agreed
          </dd>
        </div>
        <div className="flex items-center gap-space-xs">
          <Icon
            name="format_list_bulleted"
            className="text-[18px] text-wholesale-teal"
          />
          <dt className="sr-only">Lines</dt>
          <dd className="m-0">
            {lineCount} {lineCount === 1 ? "line" : "lines"}
          </dd>
        </div>
      </dl>
      {/* One reserved status line: why it stopped, else the last run. */}
      <p
        className={`m-0 h-5 truncate text-body-sm ${s.status === "stopped" ? "font-semibold text-amber-800 dark:text-amber-200" : "text-on-surface-variant"}`}
      >
        {s.status === "stopped"
          ? stopReasonText(s.stop_reason)
          : s.last_run
            ? `Last run: ${RUN_STATUS_LABEL[s.last_run.status]} · ${formatDate(s.last_run.scheduled_date)}`
            : ""}
      </p>
      <div className="mt-auto flex min-h-[34px] items-center gap-x-space-lg overflow-hidden whitespace-nowrap">
        <Link to={`/schedules/${s.id}`} className={linkClass}>
          <span className="group-hover:underline">View details</span>
          <Icon name="arrow_forward" className="text-[16px]" />
        </Link>
        {s.status === "stopped" && s.conversation_id && (
          <Link
            to={`/conversations/${s.conversation_id}`}
            className={linkClass}
          >
            <span className="group-hover:underline">Open the conversation</span>
          </Link>
        )}
        <ScheduleActions
          schedule={s}
          onChanged={onChanged}
          onStale={onStale}
          compact
        />
      </div>
    </article>
  );
}
