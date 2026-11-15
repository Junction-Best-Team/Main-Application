import { KitchenPattern } from "../../../shared/components/KitchenPattern";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import type { ScheduleLine } from "../../../shared/api/types";
import { createSchedule, previewNewSchedule } from "../api/schedulesApi";
import { useAuth } from "../../auth/useAuth";
import { ScheduleEditorBody } from "../components/ScheduleEditorBody";
import {
  DEFAULT_DRAFT,
  buildLineRules,
  buildRecurrence,
  ruleErrors,
  todayHelsinki,
  validateDate,
  type RecurrenceDraft,
  type RuleDrafts,
} from "../components/scheduleDraft";
import { primaryButton } from "../components/formStyles";
import { useScheduleTerms } from "../hooks/useScheduleTerms";

// /schedules/new?order=<order_id>: make a standing order from a past (placed) order.
export function ScheduleCreatePage() {
  const [params] = useSearchParams();
  const orderId = params.get("order");
  return (
    <main className="isolate mx-auto flex w-full max-w-6xl flex-col gap-space-lg px-margin-sm py-space-lg md:px-margin md:py-space-xl">
      <KitchenPattern seed={3} />
      <div className="flex flex-col gap-space-xs">
        <Link
          to="/purchases"
          className="font-label text-label-md text-wholesale-teal no-underline"
        >
          ← Back to past orders
        </Link>
        <h1 className="m-0 font-headline text-headline-lg-mobile tracking-normal text-primary md:text-headline-lg">
          Create standing order
        </h1>
        <p className="m-0 max-w-2xl font-body text-body-md text-on-surface-variant">
          Repeat a past order on a schedule. Each run orders the same products
          again, and you stay in control through the price ceiling below.
        </p>
      </div>
      {orderId ? (
        <CreateFlow orderId={orderId} />
      ) : (
        <div
          role="alert"
          className="flex flex-col items-start gap-space-sm rounded-lg bg-error-container p-space-md text-on-error-container"
        >
          <p className="m-0 font-body text-body-md">
            Choose a past order to repeat. A standing order is always created
            from an order you have already placed.
          </p>
          <Link to="/purchases" className={primaryButton}>
            Open past orders
          </Link>
        </div>
      )}
    </main>
  );
}

function CreateFlow({ orderId }: { orderId: string }) {
  const demo = !!useAuth().session?.scheduler_demo_mode;
  const navigate = useNavigate();
  const [recurrence, setRecurrence] = useState<RecurrenceDraft>(DEFAULT_DRAFT);
  const [firstRunDate, setFirstRunDate] = useState(() => todayHelsinki(1));
  const [rules, setRules] = useState<RuleDrafts>({});
  // The lines are only known after the first preview; the rules attach to them.
  const [lines, setLines] = useState<ScheduleLine[]>([]);

  const built = buildRecurrence(recurrence, firstRunDate);
  const ready =
    built.recurrence != null &&
    validateDate(firstRunDate, demo) === "" &&
    !ruleErrors(rules);
  const body =
    built.recurrence && validateDate(firstRunDate, demo) === ""
      ? {
          order_id: orderId,
          recurrence: built.recurrence,
          first_run_date: firstRunDate,
          line_rules: buildLineRules(rules),
        }
      : null;

  const flow = useScheduleTerms({
    inputsKey: JSON.stringify(body),
    preview: (csrf) => previewNewSchedule(csrf, body!),
    commit: (csrf, c) =>
      createSchedule(csrf, {
        ...body!,
        price_ceiling_gross: c.ceiling,
        agreed_terms_fingerprint: c.fingerprint,
        idempotency_key: c.key,
      }),
    onTerms: (terms) => setLines(terms.lines),
    onDone: (schedule) => navigate(`/schedules/${schedule.id}`),
  });

  return (
    <ScheduleEditorBody
      flow={flow}
      recurrence={recurrence}
      onRecurrence={setRecurrence}
      firstRunDate={firstRunDate}
      onFirstRunDate={setFirstRunDate}
      lines={lines}
      rules={rules}
      onRules={setRules}
      previewDisabled={!ready}
      commitLabel="Create standing order"
      notFound={{
        message:
          "We could not find this order. Standing orders can only be created from your own placed orders.",
        to: "/purchases",
        linkLabel: "Open past orders",
      }}
    />
  );
}
