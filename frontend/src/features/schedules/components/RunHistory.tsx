import { Link } from "react-router-dom";
import type { ScheduleRun } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import {
  formatDate,
  RUN_STATUS_LABEL,
  skippedReasonText,
  STOP_REASON_TEXT,
  stopReasonText,
  type ChipTone,
} from "../model/scheduleStatus";
import { ToneChip } from "./ScheduleChip";
import { RunLineStatus } from "./RunLineStatus";

const RUN_TONE: Record<ScheduleRun["status"], ChipTone> = {
  due: "neutral",
  prepared: "neutral",
  committed: "positive",
  disrupted: "attention",
  skipped: "neutral",
};

const linkClass =
  "font-label text-label-md text-wholesale-teal underline-offset-2 hover:underline";

function reasonText(run: ScheduleRun) {
  if (run.status === "skipped") return skippedReasonText(run.reason_code);
  if (run.status === "disrupted") return stopReasonText(run.reason_code);
  return "";
}

function RunItem({
  run,
  currencyCode,
}: {
  run: ScheduleRun;
  currencyCode?: string | null;
}) {
  const eur = currencyCode ?? "EUR";
  const lines = run.reason?.lines ?? [];
  // Substitutions are normally also in reason.lines; show the ones that are not.
  const extra = (run.substitutions ?? []).filter(
    (s) => !lines.some((l) => l.product_id === s.product_id),
  );
  const reason = reasonText(run);
  // Further reasons besides the main one: known codes as a sentence, unknown ones as the code.
  const moreCodes =
    run.status === "disrupted"
      ? (run.reason?.codes ?? []).filter((c) => c !== run.reason_code)
      : [];
  const agreed = run.reason?.agreed_gross_total;
  const current = run.reason?.current_gross_total;
  return (
    <li
      className={`flex flex-col gap-space-sm rounded-lg border border-border-subtle p-space-md ${run.status === "skipped" ? "opacity-70" : ""} ${run.status === "disrupted" ? "border-amber-300 bg-amber-100/30" : ""}`}
    >
      <div className="flex flex-col gap-space-xs sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="m-0 font-label text-label-lg text-primary">
            {formatDate(run.scheduled_date)}
          </p>
          <p className="m-0 text-body-sm text-on-surface-variant">
            Delivery {formatDate(run.delivery_date)}
          </p>
        </div>
        <ToneChip
          label={RUN_STATUS_LABEL[run.status]}
          tone={RUN_TONE[run.status]}
        />
      </div>
      {reason && (
        <p className="m-0 text-body-sm text-on-surface-variant">
          Reason: {reason}
        </p>
      )}
      {moreCodes.length > 0 && (
        <p
          data-testid="run-codes"
          className="m-0 text-body-sm text-on-surface-variant"
        >
          Also: {moreCodes.map((c) => STOP_REASON_TEXT[c] ?? c).join(" · ")}
        </p>
      )}
      {(lines.length > 0 || extra.length > 0) && (
        <div className="flex flex-col gap-space-xs">
          {[...lines, ...extra].map((line) => (
            <RunLineStatus
              key={`${line.product_id}-${line.status}`}
              line={line}
              currencyCode={currencyCode}
            />
          ))}
        </div>
      )}
      {agreed != null && current != null && (
        <p className="m-0 text-body-sm text-on-surface-variant">
          {`Agreed total ${currency(agreed, eur)} · current total ${currency(current, eur)}`}
        </p>
      )}
      {(run.proposal_id || run.conversation_id) && (
        <div className="flex flex-wrap gap-space-md">
          {run.proposal_id && run.status === "committed" && (
            <Link to={`/purchases/${run.proposal_id}`} className={linkClass}>
              View order
            </Link>
          )}
          {run.proposal_id && run.status === "disrupted" && (
            <Link to={`/purchases/${run.proposal_id}`} className={linkClass}>
              Review the proposed order
            </Link>
          )}
          {run.conversation_id && run.status === "disrupted" && (
            <Link
              to={`/conversations/${run.conversation_id}`}
              className={linkClass}
            >
              Open the conversation
            </Link>
          )}
        </div>
      )}
    </li>
  );
}

// Runs newest first, as the server sends them. "Show older runs" is the parent's paging.
export function RunHistory({
  runs,
  currencyCode,
  hasMore,
  loadingMore,
  onShowOlder,
}: {
  runs: ScheduleRun[];
  currencyCode?: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  onShowOlder: () => void;
}) {
  return (
    <div className="flex flex-col gap-space-sm">
      {runs.length === 0 ? (
        <p className="m-0 text-secondary">No runs yet.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-space-sm p-0">
          {runs.map((run) => (
            <RunItem key={run.id} run={run} currencyCode={currencyCode} />
          ))}
        </ul>
      )}
      {hasMore && (
        <button
          type="button"
          onClick={onShowOlder}
          disabled={loadingMore}
          className="cursor-pointer self-center rounded-lg border border-outline-variant bg-surface-pure px-space-lg py-3 font-label text-label-md text-primary hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loadingMore ? "Loading…" : "Show older runs"}
        </button>
      )}
    </div>
  );
}
