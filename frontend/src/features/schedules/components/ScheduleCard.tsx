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

const linkClass =
  "inline-flex items-center gap-1 font-label text-label-md text-wholesale-teal no-underline hover:underline";

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
      className="flex flex-col gap-space-sm rounded-xl bg-surface-pure p-space-lg shadow-level-2"
    >
      <div className="flex flex-col gap-space-xs sm:flex-row sm:items-start sm:justify-between">
        <h2
          id={`schedule-${s.id}`}
          className="m-0 min-w-0 font-headline text-headline-sm text-primary wrap-anywhere"
        >
          <Link to={`/schedules/${s.id}`} className="text-primary no-underline">
            {s.title}
          </Link>
        </h2>
        <div className="shrink-0">
          <ScheduleChip schedule={s} />
        </div>
      </div>
      <dl className="m-0 grid grid-cols-1 gap-x-space-lg gap-y-space-xs text-body-md text-on-surface-variant sm:grid-cols-2">
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
      {s.last_run && (
        <p className="m-0 text-body-sm text-on-surface-variant">
          Last run: {RUN_STATUS_LABEL[s.last_run.status]} ·{" "}
          {formatDate(s.last_run.scheduled_date)}
        </p>
      )}
      {s.status === "stopped" && (
        <p className="m-0 rounded-lg bg-amber-100 px-space-md py-space-sm text-body-sm text-amber-900">
          {stopReasonText(s.stop_reason)}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-space-lg gap-y-space-sm">
        <Link to={`/schedules/${s.id}`} className={linkClass}>
          View details
          <Icon name="arrow_forward" className="text-[16px]" />
        </Link>
        {s.status === "stopped" && s.conversation_id && (
          <Link
            to={`/conversations/${s.conversation_id}`}
            className={linkClass}
          >
            Open the conversation
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
