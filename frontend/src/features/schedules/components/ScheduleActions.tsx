import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../../shared/api/client";
import type { Schedule } from "../../../shared/api/types";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { useAuth } from "../../auth/useAuth";
import {
  cancelSchedule,
  pauseSchedule,
  resumeSchedule,
  runScheduleNow,
} from "../api/schedulesApi";

type Kind = "pause" | "resume" | "cancel" | "runNow";
const BUSY_LABEL: Record<Kind, string> = {
  pause: "Pausing…",
  resume: "Resuming…",
  cancel: "Cancelling…",
  runNow: "Running…",
};
const ACTION: Record<Kind, typeof pauseSchedule> = {
  pause: pauseSchedule,
  resume: resumeSchedule,
  cancel: cancelSchedule,
  runNow: runScheduleNow,
};
const demoButton =
  "inline-flex cursor-pointer items-center justify-center gap-1 rounded-lg border-2 border-dashed border-amber-500 bg-amber-100 px-space-md py-2 font-mono text-label-md text-amber-900 disabled:cursor-not-allowed disabled:opacity-50";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const button =
  "inline-flex cursor-pointer items-center justify-center rounded-lg px-space-md py-2 font-label text-label-md no-underline disabled:cursor-not-allowed disabled:opacity-50";
const quiet = `${button} border border-outline-variant bg-surface-pure text-primary hover:bg-surface-container-high`;
const danger = `${button} border border-error/40 bg-surface-pure text-error hover:bg-error-container`;

// Pause, Resume, Cancel (with a confirmation step) and Edit. `compact` is the list card: only
// Pause and Resume. onChanged receives the schedule the server answered with; onStale is called
// when the server says the schedule is no longer active, so the page can reload it.
export function ScheduleActions({
  schedule,
  onChanged,
  onStale,
  compact = false,
}: {
  schedule: Pick<Schedule, "id" | "status">;
  onChanged: (next: Schedule) => void;
  onStale?: () => Promise<void> | void;
  compact?: boolean;
}) {
  const { session, setSession } = useAuth();
  const [busy, setBusy] = useState<Kind | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  // The browser normally only gets approvers; hide the write buttons for any other role.
  const canWrite = !session?.role || session.role === "approver";
  const { status } = schedule;
  const canPause = status === "active";
  const canResume = status === "paused";
  const canCancel =
    !compact &&
    (status === "active" || status === "paused" || status === "stopped");
  const canEdit = !compact && (status === "active" || status === "paused");
  // Demo mode (session.scheduler_demo_mode, set on the server): make today's run due at once.
  const canRunNow =
    !compact && status === "active" && !!session?.scheduler_demo_mode;

  async function run(kind: Kind) {
    if (!session) return;
    setBusy(kind);
    setError("");
    try {
      const next = await ACTION[kind](session.csrf_token, schedule.id);
      setConfirming(false);
      onChanged(next);
      if (kind === "runNow") {
        // The worker prepares and commits the run within a few seconds: reload a few times.
        for (let i = 0; i < 5; i++) {
          await sleep(2000);
          await onStale?.();
        }
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setSession(null);
        return;
      }
      setError(e instanceof Error ? e.message : "The action failed.");
      setConfirming(false);
      if (e instanceof ApiError && e.code === "SCHEDULE_NOT_ACTIVE")
        await onStale?.();
    } finally {
      setBusy(null);
    }
  }

  const disabled = busy !== null;
  const label = (kind: Kind, text: string) =>
    busy === kind ? BUSY_LABEL[kind] : text;
  return (
    <div className="flex flex-col gap-space-sm">
      {canWrite && (
        <div className="flex flex-wrap items-center gap-space-sm">
          {canPause && (
            <button
              type="button"
              className={quiet}
              disabled={disabled}
              onClick={() => void run("pause")}
            >
              {label("pause", "Pause")}
            </button>
          )}
          {canResume && (
            <button
              type="button"
              className={quiet}
              disabled={disabled}
              onClick={() => void run("resume")}
            >
              {label("resume", "Resume")}
            </button>
          )}
          {canRunNow && (
            <span className="inline-flex items-center gap-space-xs">
              <button
                type="button"
                className={demoButton}
                disabled={disabled}
                onClick={() => void run("runNow")}
              >
                {label("runNow", "Run now (demo)")}
              </button>
              <span className="font-mono text-label-sm uppercase text-amber-900">
                Demo command
              </span>
            </span>
          )}
          {canEdit && (
            <Link to={`/schedules/${schedule.id}/edit`} className={quiet}>
              Edit
            </Link>
          )}
          {canCancel && !confirming && (
            <button
              type="button"
              className={danger}
              disabled={disabled}
              onClick={() => setConfirming(true)}
            >
              Cancel standing order
            </button>
          )}
        </div>
      )}
      {canWrite && canCancel && confirming && (
        <div
          role="group"
          aria-label="Confirm cancelling"
          className="flex flex-col gap-space-sm rounded-lg bg-surface-container-low p-space-md"
        >
          <p className="m-0 text-body-md text-on-surface">
            Cancel this standing order? Later runs will not happen.
          </p>
          <div className="flex flex-wrap gap-space-sm">
            <button
              type="button"
              className={`${button} bg-error text-on-error`}
              disabled={disabled}
              onClick={() => void run("cancel")}
            >
              {busy === "cancel" ? BUSY_LABEL.cancel : "Yes, cancel"}
            </button>
            <button
              type="button"
              className={quiet}
              disabled={disabled}
              onClick={() => setConfirming(false)}
            >
              Keep it
            </button>
          </div>
        </div>
      )}
      <ErrorMessage message={error} />
    </div>
  );
}
