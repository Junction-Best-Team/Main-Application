import { useEffect, useId, useRef, useState } from "react";
import type { Conversation } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";

type Activity = NonNullable<Conversation["activity"]>;
type Step = {
  sequence: number;
  label: string;
  status: "running" | "complete" | "failed" | "interrupted";
};

// Each of these events starts a new visible step and finishes the one before it.
const STEP_KINDS = new Set([
  "started",
  "thinking",
  "reviewing",
  "tool_started",
]);

function activitySteps(activity: Activity | undefined, busy: boolean): Step[] {
  const steps: Step[] = [];
  const finishRunning = (status: Step["status"]) => {
    const current = steps.at(-1);
    if (current?.status === "running") current.status = status;
  };
  for (const event of activity?.events ?? []) {
    if (STEP_KINDS.has(event.kind)) {
      finishRunning("complete");
      steps.push({
        sequence: event.sequence,
        label: event.label,
        status: "running",
      });
    } else if (event.kind === "tool_completed" || event.kind === "complete") {
      finishRunning("complete");
    } else if (event.kind === "tool_failed" || event.kind === "error") {
      finishRunning("failed");
    }
  }
  if (!busy) finishRunning("interrupted");
  return steps;
}

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

/** Seconds this browser has watched the current turn; unknown after a reload of a finished turn. */
function useElapsed(turnKey: string | undefined, busy: boolean) {
  const startedAt = useRef<{ key: string | undefined; at: number } | null>(
    null,
  );
  const [seconds, setSeconds] = useState<number | null>(null);
  useEffect(() => {
    if (!busy) return;
    if (!startedAt.current || startedAt.current.key !== turnKey)
      startedAt.current = { key: turnKey, at: Date.now() };
    const start = startedAt.current.at;
    const tick = () => setSeconds(Math.floor((Date.now() - start) / 1000));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [turnKey, busy]);
  // A finished turn keeps its final time only if this browser saw it run.
  if (!busy && startedAt.current?.key !== turnKey) return null;
  return seconds;
}

/** Four dots that pulse in turn while the worker runs; still when reduced motion is set. */
function ActivityGlyph() {
  return (
    <span
      aria-hidden="true"
      className="activity-dots grid shrink-0 grid-cols-2 gap-[3px]"
    >
      {[0, 1, 3, 2].map((order) => (
        <span
          key={order}
          className="activity-dot block size-[5px] rounded-full bg-wholesale-teal"
          style={{ animationDelay: `${order * 0.2}s` }}
        />
      ))}
    </span>
  );
}

/** Real worker activity, never simulated reasoning or a purchasing decision. */
export function ChatActivity({
  activity,
  busy,
}: {
  activity: Conversation["activity"];
  busy: boolean;
}) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  // A pending POST can still hold the previous turn's completed snapshot.
  const current =
    busy && (activity?.state === "complete" || activity?.state === "failed")
      ? undefined
      : (activity ?? undefined);
  const elapsed = useElapsed(current?.turn_id, busy);
  const steps = activitySteps(current, busy);
  if (!busy && !steps.length) return null;
  const last = current?.events?.at(-1);
  const failed = !busy && current?.state === "failed";
  const title = busy
    ? current?.state === "queued"
      ? "Waiting to start…"
      : last?.kind === "tool_completed"
        ? `${last.label} · Done`
        : last?.kind === "tool_failed"
          ? `${last.label} · Couldn't finish`
          : last
            ? `${last.label}…`
            : current
              ? "Preparing your response…"
              : "Sending your request…"
    : failed
      ? "Response interrupted"
      : "Finished";

  const header = (
    <>
      {busy ? (
        <ActivityGlyph />
      ) : (
        <Icon
          name={failed ? "error_outline" : "check_circle"}
          className="shrink-0 text-[16px] text-wholesale-teal"
        />
      )}
      <span role="status" className="min-w-0 truncate">
        {title}
      </span>
      {elapsed !== null && (
        <span className="shrink-0 tabular-nums text-label-sm text-outline">
          {formatElapsed(elapsed)}
        </span>
      )}
    </>
  );

  return (
    <section aria-label="Aimo activity" className="w-full max-w-xl">
      {steps.length ? (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((value) => !value)}
          className="group flex max-w-full items-center gap-space-sm rounded-md py-space-xs pr-space-xs text-left text-body-sm text-secondary transition-colors hover:text-on-surface focus-visible:outline-2 focus-visible:outline-wholesale-teal"
        >
          {header}
          <Icon
            name="chevron_right"
            className={`shrink-0 text-[18px] transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="sr-only">
            {open ? "Hide" : "Show"} {steps.length}{" "}
            {steps.length === 1 ? "step" : "steps"}
          </span>
        </button>
      ) : (
        <div className="flex items-center gap-space-sm py-space-xs text-body-sm text-secondary">
          {header}
        </div>
      )}
      {open && steps.length > 0 && (
        <ol
          id={listId}
          aria-label="Activity steps"
          className="mt-space-xs ml-[5px] flex max-h-56 list-none flex-col gap-space-xs overflow-y-auto border-l border-border-subtle py-space-xs pl-space-md"
        >
          {steps.map((step) => (
            <li
              key={step.sequence}
              className="flex items-start gap-space-sm text-body-sm text-on-surface-variant"
            >
              <Icon
                name={
                  step.status === "complete"
                    ? "check"
                    : step.status === "failed" || step.status === "interrupted"
                      ? "error_outline"
                      : "progress_activity"
                }
                className={`shrink-0 text-[16px] ${step.status === "running" ? "activity-spin text-wholesale-teal" : ""}`}
              />
              <span>
                {step.label}
                {step.status === "complete" ? (
                  // The check icon already shows completion; keep the word for screen readers.
                  <span className="sr-only"> · Done</span>
                ) : (
                  <span className="ml-space-xs text-label-sm text-secondary">
                    {" · "}
                    {step.status === "failed"
                      ? "Couldn't finish"
                      : step.status === "interrupted"
                        ? "Interrupted"
                        : "In progress"}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
