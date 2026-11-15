import { useEffect, useId, useRef, useState } from "react";
import type { Conversation } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";

type Activity = NonNullable<Conversation["activity"]>;
type Step = {
  sequence: number;
  label: string;
  /** Server-built summary of a completed tool's result, never model text. */
  detail?: string | null;
  status: "running" | "complete" | "failed" | "interrupted";
};

// Model stages run in sequence; independent tool steps can overlap.
const STEP_KINDS = new Set([
  "started",
  "thinking",
  "reviewing",
  "tool_started",
]);

function activitySteps(activity: Activity | undefined, busy: boolean): Step[] {
  const steps: Step[] = [];
  const tools: Step[] = [];
  let stage: Step | undefined;
  const finishStage = (status: Step["status"]) => {
    if (stage?.status === "running") stage.status = status;
  };
  for (const event of activity?.events ?? []) {
    if (STEP_KINDS.has(event.kind)) {
      finishStage("complete");
      const step: Step = {
        sequence: event.sequence,
        label: event.label,
        status: "running",
      };
      steps.push(step);
      if (event.kind === "tool_started") tools.push(step);
      else stage = step;
    } else if (
      event.kind === "tool_completed" ||
      event.kind === "tool_failed"
    ) {
      // Parallel reads start together and finish in request order. Match the
      // earliest unfinished call with this fixed server-owned display label.
      const current = tools.find(
        (step) => step.status === "running" && step.label === event.label,
      );
      if (current) {
        current.status =
          event.kind === "tool_completed" ? "complete" : "failed";
        if (event.kind === "tool_completed") current.detail = event.detail;
      }
    } else if (event.kind === "complete") {
      finishStage("complete");
    } else if (event.kind === "error") {
      finishStage("failed");
    }
  }
  if (!busy)
    for (const step of steps)
      if (step.status === "running") step.status = "interrupted";
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
  stopped = false,
}: {
  activity: Conversation["activity"];
  busy: boolean;
  /** The customer stopped this turn: a calm "Stopped", not an error. */
  stopped?: boolean;
}) {
  const listId = useId();
  const listRef = useRef<HTMLOListElement>(null);
  // Collapsed to one live status line by default; the customer can expand the
  // step list, and that toggle wins for this turn.
  const [toggled, setToggled] = useState<{
    turn: string | undefined;
    open: boolean;
  } | null>(null);
  // A pending POST can still hold the previous turn's completed snapshot.
  const current =
    busy && (activity?.state === "complete" || activity?.state === "failed")
      ? undefined
      : (activity ?? undefined);
  const elapsed = useElapsed(current?.turn_id, busy);
  const steps = activitySteps(current, busy);
  const open =
    toggled && toggled.turn === current?.turn_id ? toggled.open : false;
  const stepCount = steps.length;
  // Follow the newest step while the turn runs.
  useEffect(() => {
    const list = listRef.current;
    if (busy && open && list) list.scrollTop = list.scrollHeight;
  }, [busy, open, stepCount]);
  const failed = !busy && current?.state === "failed";
  const wasStopped = failed && stopped;
  if (!busy && !steps.length && !wasStopped) return null;
  const last = current?.events?.at(-1);
  const title = busy
    ? current?.state === "queued"
      ? "Waiting to start…"
      : last?.kind === "tool_completed"
        ? `${last.label} · ${last.detail || "Done"}`
        : last?.kind === "tool_failed"
          ? `${last.label} · Couldn't finish`
          : last
            ? `${last.label}…`
            : current
              ? "Preparing your response…"
              : "Sending your request…"
    : wasStopped
      ? "Stopped"
      : failed
        ? "Response interrupted"
        : "Finished";

  const header = (
    <>
      {busy ? (
        <ActivityGlyph />
      ) : (
        <Icon
          name={
            wasStopped
              ? "stop_circle"
              : failed
                ? "error_outline"
                : "check_circle"
          }
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
          onClick={() => setToggled({ turn: current?.turn_id, open: !open })}
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
          ref={listRef}
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
                    : step.status === "interrupted" && wasStopped
                      ? "stop_circle"
                      : step.status === "failed" ||
                          step.status === "interrupted"
                        ? "error_outline"
                        : "progress_activity"
                }
                className={`shrink-0 text-[16px] ${step.status === "running" ? "activity-spin text-wholesale-teal" : ""}`}
              />
              <span className="min-w-0">
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
                        ? wasStopped
                          ? "Stopped"
                          : "Interrupted"
                        : "In progress"}
                  </span>
                )}
                {step.detail && (
                  <span className="block break-words text-label-sm text-secondary">
                    {step.detail}
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
