import { useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import type { ScheduleDetail, ScheduleLine } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { previewScheduleEdit, replaceSchedule } from "../api/schedulesApi";
import { RestartOrderSelect } from "../components/RestartOrderSelect";
import { useAuth } from "../../auth/useAuth";
import { ScheduleEditorBody } from "../components/ScheduleEditorBody";
import {
  buildLineRules,
  buildRecurrence,
  draftFromRecurrence,
  ruleErrors,
  rulesFromLines,
  todayHelsinki,
  validateDate,
  type RecurrenceDraft,
  type RuleDrafts,
} from "../components/scheduleDraft";
import {
  card,
  cardTitle,
  hint,
  secondaryButton,
} from "../components/formStyles";
import { useEditableSchedule } from "../hooks/useEditableSchedule";
import { usePlacedOrders } from "../hooks/usePlacedOrders";
import { useScheduleTerms } from "../hooks/useScheduleTerms";
import { isSuperseded, stopReasonText } from "../model/scheduleStatus";

const EDITABLE = ["active", "paused", "stopped"];
const shell =
  "mx-auto flex w-full max-w-6xl flex-col gap-space-lg px-margin-sm py-space-lg md:px-margin md:py-space-xl";
const heading =
  "m-0 font-headline text-headline-lg-mobile tracking-normal text-primary md:text-headline-lg";
const alertBox =
  "flex flex-col items-start gap-space-sm rounded-lg bg-error-container p-space-md text-on-error-container";

// /schedules/:scheduleId/edit (and ?restart=1): change a standing order or restart a stopped one.
// Either way the server creates a NEW authorization that replaces the old one.
export function ScheduleEditPage() {
  const { scheduleId } = useParams();
  const { schedule, loading, error, notFound, reload } =
    useEditableSchedule(scheduleId);
  if (loading)
    return (
      <main className={shell}>
        <p role="status" className="m-0 text-on-surface-variant">
          Loading standing order…
        </p>
      </main>
    );
  if (!schedule)
    return (
      <main className={shell}>
        <h1 className={heading}>Edit standing order</h1>
        <div role="alert" className={alertBox}>
          <p className="m-0 font-body text-body-md">
            {notFound
              ? "We could not find this standing order."
              : error || "The standing order could not be loaded."}
          </p>
          <Link to="/schedules" className={secondaryButton}>
            Back to standing orders
          </Link>
        </div>
      </main>
    );
  return <EditFlow key={schedule.id} schedule={schedule} reload={reload} />;
}

function EditFlow({
  schedule,
  reload,
}: {
  schedule: ScheduleDetail;
  reload: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const demo = !!useAuth().session?.scheduler_demo_mode;
  const [params] = useSearchParams();
  const restart =
    params.get("restart") === "1" || schedule.status === "stopped";
  const [changedElsewhere, setChangedElsewhere] = useState(false);

  // Prefill from what was agreed. The first run date starts at the next run (or tomorrow when the
  // series start is too soon) because a first run must be tomorrow or later.
  const [firstRunDate, setFirstRunDate] = useState(() => {
    const earliest = todayHelsinki(demo ? 0 : 1);
    return (
      [schedule.next_run_date, schedule.first_run_date].find(
        (d): d is string => !!d && d >= earliest,
      ) ?? earliest
    );
  });
  const [recurrence, setRecurrence] = useState<RecurrenceDraft>(() =>
    draftFromRecurrence(schedule.recurrence, firstRunDate),
  );
  const [rules, setRules] = useState<RuleDrafts>(() =>
    rulesFromLines(schedule.lines),
  );
  const [source, setSource] = useState("");
  // Lines of the chosen revised order, known after its first preview.
  const [sourceLines, setSourceLines] = useState<ScheduleLine[]>([]);
  const placed = usePlacedOrders(restart);

  const built = buildRecurrence(recurrence, firstRunDate);
  const dateOk = validateDate(firstRunDate, demo) === "";
  const body =
    built.recurrence && dateOk
      ? {
          recurrence: built.recurrence,
          first_run_date: firstRunDate,
          ...(Object.keys(rules).length > 0
            ? { line_rules: buildLineRules(rules) }
            : {}),
          ...(source ? { source_order_id: source } : {}),
        }
      : null;

  const flow = useScheduleTerms({
    inputsKey: JSON.stringify(body),
    // A restart starts at the total of the new order; an edit keeps the ceiling already agreed.
    initialCeiling: restart
      ? undefined
      : (schedule.price_ceiling_gross ?? undefined),
    preview: (csrf) => previewScheduleEdit(csrf, schedule.id, body!),
    commit: (csrf, c) =>
      replaceSchedule(csrf, schedule.id, {
        ...body!,
        price_ceiling_gross: c.ceiling,
        agreed_terms_fingerprint: c.fingerprint,
        idempotency_key: c.key,
      }),
    onTerms: (terms) => {
      if (source) setSourceLines(terms.lines);
    },
    onDone: (next) => navigate(`/schedules/${next.id}`),
    onNotActive: () => {
      setChangedElsewhere(true);
      void reload();
    },
  });

  const chooseSource = (orderId: string) => {
    setSource(orderId);
    // The old rules belong to the old products; the new order's own rules show after its preview.
    setRules(orderId ? {} : rulesFromLines(schedule.lines));
    setSourceLines([]);
  };

  const title = restart ? "Restart standing order" : "Edit standing order";
  const top = (
    <div className="flex flex-col gap-space-xs">
      <Link
        to={`/schedules/${schedule.id}`}
        className="font-label text-label-md text-wholesale-teal no-underline"
      >
        ← Back to the standing order
      </Link>
      <h1 className={heading}>{title}</h1>
      <p className="m-0 max-w-2xl font-body text-body-md text-on-surface-variant wrap-anywhere">
        {schedule.title}
      </p>
    </div>
  );

  if (isSuperseded(schedule) && schedule.replaced_by)
    return (
      <main className={shell}>
        {top}
        <div role="alert" className={alertBox}>
          <p className="m-0 font-body text-body-md">
            This standing order has already been replaced by a newer one.
          </p>
          <Link
            to={`/schedules/${schedule.replaced_by}`}
            className={secondaryButton}
          >
            Open the new standing order
          </Link>
        </div>
      </main>
    );
  if (!EDITABLE.includes(schedule.status))
    return (
      <main className={shell}>
        {top}
        <div role="alert" className={alertBox}>
          <p className="m-0 font-body text-body-md">
            {changedElsewhere
              ? `This standing order was changed elsewhere and is now ${schedule.status}.`
              : `A ${schedule.status} standing order cannot be changed.`}
          </p>
          <Link to={`/schedules/${schedule.id}`} className={secondaryButton}>
            Back to the standing order
          </Link>
        </div>
      </main>
    );

  const lines = source ? sourceLines : schedule.lines;
  const needsSource = restart && !source;
  return (
    <main className={shell}>
      {top}
      {schedule.status === "stopped" && schedule.stop_reason && (
        <p className="m-0 rounded-lg bg-secondary-container p-space-md font-body text-body-md text-on-secondary-container">
          {stopReasonText(schedule.stop_reason)} Place the revised order, then
          restart from it.
        </p>
      )}
      <ScheduleEditorBody
        flow={flow}
        recurrence={recurrence}
        onRecurrence={setRecurrence}
        firstRunDate={firstRunDate}
        onFirstRunDate={setFirstRunDate}
        lines={lines}
        rules={rules}
        onRules={setRules}
        previewDisabled={body == null || ruleErrors(rules) || needsSource}
        extraStep={
          restart ? (
            <RestartOrderSelect
              orders={placed.orders}
              loading={placed.loading}
              error={placed.error}
              more={placed.more}
              retry={() => void placed.retry()}
              value={source}
              onChange={chooseSource}
            />
          ) : undefined
        }
        products={
          lines.length > 0 ? (
            <section aria-labelledby="products-heading" className={card}>
              <h2 id="products-heading" className={cardTitle}>
                Products
              </h2>
              <p className={hint}>
                Products and quantities cannot be changed here. To change them,
                place a new order and create a new standing order from it.
              </p>
              <ul className="m-0 flex list-none flex-col divide-y divide-border-subtle p-0">
                {lines.map((line) => (
                  <li
                    key={line.product_id}
                    className="flex flex-wrap items-baseline justify-between gap-x-space-md py-space-sm"
                  >
                    <span className="min-w-0 font-body text-body-md wrap-anywhere">
                      {line.name}
                    </span>
                    <span className={hint}>
                      {line.amount} {line.unit}
                      {line.line_gross != null &&
                        ` · ${currency(line.line_gross, schedule.currency ?? "EUR")}`}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : undefined
        }
        commitLabel={
          restart ? "Restart standing order" : "Replace standing order"
        }
        commitNote="Saving creates a new authorization with these terms. The current one stops when the new one starts."
        notFound={{
          message: "We could not find this standing order or the chosen order.",
          to: "/schedules",
          linkLabel: "Back to standing orders",
        }}
      />
    </main>
  );
}
