import type { Conversation } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";

type Activity = NonNullable<Conversation["activity"]>;
type Step = {
  sequence: number;
  label: string;
  status: "running" | "complete" | "failed" | "interrupted";
};

function toolSteps(activity: Activity | undefined, busy: boolean): Step[] {
  const steps: Step[] = [];
  for (const event of activity?.events ?? []) {
    if (event.kind === "tool_started") {
      steps.push({ ...event, status: "running" });
    } else if (
      event.kind === "tool_completed" ||
      event.kind === "tool_failed"
    ) {
      const current = steps.at(-1);
      if (current?.status === "running")
        current.status =
          event.kind === "tool_completed" ? "complete" : "failed";
    }
  }
  if (!busy)
    for (const step of steps)
      if (step.status === "running") step.status = "interrupted";
  return steps;
}

/** Real worker activity, never simulated reasoning or a purchasing decision. */
export function ChatActivity({
  activity,
  busy,
}: {
  activity: Conversation["activity"];
  busy: boolean;
}) {
  // A pending POST can still hold the previous turn's completed snapshot.
  const current =
    busy && (activity?.state === "complete" || activity?.state === "failed")
      ? undefined
      : (activity ?? undefined);
  const steps = toolSteps(current, busy);
  if (!busy && !steps.length) return null;
  const last = current?.events?.at(-1);
  const title = busy
    ? current?.state === "queued"
      ? "Waiting to start…"
      : last?.kind === "tool_started"
        ? `${last.label}…`
        : last?.kind === "tool_completed"
          ? `${last.label} · Done`
          : last?.kind === "tool_failed"
            ? `${last.label} · Couldn't finish`
            : last
              ? `${last.label}…`
              : current
                ? "Preparing your response…"
                : "Sending your request…"
    : current?.state === "failed"
      ? "Response interrupted"
      : "Finished";

  return (
    <section
      aria-label="Aimo activity"
      className="w-full max-w-xl overflow-hidden rounded-lg border border-border-subtle bg-surface-container-low"
    >
      <div className="flex items-center gap-space-sm px-space-md py-space-sm">
        <Icon
          name={busy ? "auto_awesome" : "history"}
          className="shrink-0 text-[18px] text-wholesale-teal"
        />
        <p role="status" className="text-body-sm font-semibold text-secondary">
          {title}
        </p>
      </div>
      {busy && (
        <div
          aria-hidden="true"
          className="h-0.5 overflow-hidden bg-secondary-container"
        >
          <span className="activity-sweep block h-full w-1/3 bg-wholesale-teal/60" />
        </div>
      )}
      {steps.length > 0 && (
        <details className="px-space-md py-space-sm">
          <summary className="cursor-pointer text-label-sm text-secondary">
            {steps.length} {steps.length === 1 ? "step" : "steps"}
          </summary>
          <ol
            aria-label="Tool activity"
            className="mt-space-sm flex max-h-48 list-none flex-col gap-space-xs overflow-y-auto p-0"
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
                      : step.status === "failed" ||
                          step.status === "interrupted"
                        ? "error_outline"
                        : "pending"
                  }
                  className="shrink-0 text-[18px]"
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
        </details>
      )}
    </section>
  );
}
