import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ScheduleLine } from "../../../shared/api/types";
import type { useScheduleTerms } from "../hooks/useScheduleTerms";
import { CeilingField } from "./CeilingField";
import { LineRulesEditor } from "./LineRulesEditor";
import { RecurrencePicker } from "./RecurrencePicker";
import { TermsSummary } from "./TermsSummary";
import {
  card,
  cardTitle,
  errorText,
  hint,
  primaryButton,
  secondaryButton,
} from "./formStyles";
import {
  todayHelsinki,
  type RecurrenceDraft,
  type RuleDrafts,
} from "./scheduleDraft";

export const AUTHORIZATION =
  "I agree to these exact terms, this price ceiling per run and this recurrence.";

type Flow = ReturnType<typeof useScheduleTerms>;
type Props = {
  flow: Flow;
  recurrence: RecurrenceDraft;
  onRecurrence: (draft: RecurrenceDraft) => void;
  firstRunDate: string;
  onFirstRunDate: (isoDate: string) => void;
  /** Lines to attach rules to; empty until the first preview (create) or always known (edit). */
  lines: ScheduleLine[];
  rules: RuleDrafts;
  onRules: (rules: RuleDrafts) => void;
  /** True while the inputs cannot be previewed yet (invalid date, rule or missing order). */
  previewDisabled: boolean;
  /** Extra first-step fields (the restart page's order select). */
  extraStep?: ReactNode;
  /** Read-only product list (the edit page). */
  products?: ReactNode;
  commitLabel: string;
  commitNote?: string;
  notFound: { message: string; to: string; linkLabel: string };
};

// The single screen both pages share: the form on the left, the previewed terms and the
// customer's explicit agreement on the right (stacked on a phone).
export function ScheduleEditorBody(p: Props) {
  const { flow } = p;
  const terms = flow.terms;
  const alert = <FlowAlert flow={flow} notFound={p.notFound} />;
  return (
    <div className="grid grid-cols-1 gap-space-lg lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:items-start">
      <div className="flex min-w-0 flex-col gap-space-lg">
        <section aria-labelledby="step-when" className={card}>
          <h2 id="step-when" className={cardTitle}>
            1. When should it run?
          </h2>
          {p.extraStep}
          <RecurrencePicker
            draft={p.recurrence}
            onDraft={p.onRecurrence}
            firstRunDate={p.firstRunDate}
            onFirstRunDate={p.onFirstRunDate}
            minDate={todayHelsinki()}
          />
        </section>

        {p.products}

        {p.lines.length > 0 && (
          <section aria-labelledby="step-rules" className={card}>
            <h2 id="step-rules" className={cardTitle}>
              2. Ingredient rules
            </h2>
            <LineRulesEditor
              lines={p.lines}
              rules={p.rules}
              onRules={p.onRules}
            />
          </section>
        )}

        {!terms && alert}
        <div>
          <button
            type="button"
            className={primaryButton}
            disabled={p.previewDisabled || flow.previewing}
            onClick={() => void flow.previewTerms()}
          >
            Preview terms
          </button>
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-space-lg lg:sticky lg:top-space-md">
        {flow.notice && (
          <p
            aria-live="polite"
            className="m-0 rounded-lg bg-secondary-container p-space-md font-body text-body-md text-on-secondary-container"
          >
            {flow.notice}
          </p>
        )}
        {flow.previewing && (
          <p role="status" className={`${card} m-0 text-on-surface-variant`}>
            Checking prices and availability…
          </p>
        )}
        {!flow.previewing && !terms && (
          <section className={card}>
            <h2 className={cardTitle}>Terms</h2>
            <p className={`${hint}`}>
              {flow.stale
                ? "You changed the terms. Preview them again to continue."
                : "Preview the terms to see the prices, the first dates and the total."}
            </p>
          </section>
        )}
        {terms && (
          <>
            <TermsSummary
              terms={terms}
              reasons={flow.blocking}
              notReady={flow.notReady}
            />
            <section aria-labelledby="step-agree" className={card}>
              <h2 id="step-agree" className={cardTitle}>
                3. Price ceiling and agreement
              </h2>
              <CeilingField
                value={flow.ceiling}
                onChange={flow.setCeiling}
                currencyCode={terms.currency ?? "EUR"}
                error={flow.ceilingError}
              />
              <label className="flex cursor-pointer items-start gap-space-sm font-body text-body-md has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60">
                <input
                  type="checkbox"
                  className="mt-1 size-5 shrink-0"
                  checked={flow.agreed}
                  disabled={flow.notReady || flow.refused}
                  onChange={(e) => flow.setAgreed(e.target.checked)}
                />
                <span>{AUTHORIZATION}</span>
              </label>
              {alert}
              {p.commitNote && <p className={hint}>{p.commitNote}</p>}
              <button
                type="button"
                className={`${primaryButton} w-full sm:w-auto sm:self-start`}
                disabled={!flow.canSubmit}
                onClick={() => void flow.submit()}
              >
                {flow.committing ? "Working…" : p.commitLabel}
              </button>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function FlowAlert({
  flow,
  notFound,
}: {
  flow: Flow;
  notFound: Props["notFound"];
}) {
  if (!flow.error && !flow.notFound) return null;
  return (
    <div
      role="alert"
      className="rounded-lg bg-error-container p-space-md text-on-error-container"
    >
      {flow.notFound ? (
        <div className="flex flex-col items-start gap-space-sm">
          <p className="m-0 font-body text-body-md">{notFound.message}</p>
          <Link to={notFound.to} className={secondaryButton}>
            {notFound.linkLabel}
          </Link>
        </div>
      ) : (
        <p className="m-0 font-body text-body-md">{flow.error}</p>
      )}
      {!flow.notFound && flow.refused && flow.blocking.length > 0 && (
        <ul className={`${errorText} m-0 mt-space-xs list-disc pl-space-lg`}>
          {flow.blocking.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
