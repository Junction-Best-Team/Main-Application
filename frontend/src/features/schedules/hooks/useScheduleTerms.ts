import { useCallback, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { Schedule, ScheduleTerms } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { newIdempotencyKey } from "../../../shared/lib/idempotency";
import { useAuth } from "../../auth/useAuth";
import { ceilingError, formatCeiling } from "../components/scheduleDraft";

export const TERMS_CHANGED_NOTICE =
  "Prices or availability changed. Review the new terms.";
const LIMIT_TEXT =
  "You already have the maximum of 20 active standing orders. Cancel one first.";

type Commit = { fingerprint: string; key: string; ceiling: string };
type Options = {
  /** Serialised inputs of the form. When it changes, the previewed terms are no longer valid. */
  inputsKey: string;
  /** Ceiling typed by the customer before any preview (the edit page starts at the agreed one). */
  initialCeiling?: string;
  preview: (csrf: string) => Promise<ScheduleTerms>;
  commit: (csrf: string, c: Commit) => Promise<Schedule>;
  onDone: (schedule: Schedule) => void;
  onTerms?: (terms: ScheduleTerms) => void;
  /** SCHEDULE_NOT_ACTIVE on commit: the page reloads the standing order and explains. */
  onNotActive?: () => void;
};

// Everything that belongs to ONE preview of the terms. `forKey` ties it to the form inputs it
// was made for, so editing the form discards it without any effect or reset code.
type Outcome = {
  forKey: string;
  terms: ScheduleTerms | null;
  idempotencyKey: string | null;
  agreed: boolean;
  notice: string;
  error: string;
  ceilingError: string;
  blocking: string[];
  /** The server refused these terms for good (SCHEDULE_NOT_REORDERABLE). */
  refused: boolean;
  notFound: boolean;
};
const outcomeFor = (forKey: string, over: Partial<Outcome> = {}): Outcome => ({
  forKey,
  terms: null,
  idempotencyKey: null,
  agreed: false,
  notice: "",
  error: "",
  ceilingError: "",
  blocking: [],
  refused: false,
  notFound: false,
  ...over,
});

export function reasonText(reason: unknown): string {
  if (typeof reason === "string") return reason;
  if (reason && typeof reason === "object") {
    const r = reason as Record<string, unknown>;
    for (const key of ["message", "reason", "detail", "code"])
      if (typeof r[key] === "string") return r[key] as string;
  }
  return "";
}
const reasonsOf = (list: unknown): string[] =>
  Array.isArray(list) ? list.map(reasonText).filter(Boolean) : [];
function reasonsFromDetails(details: unknown): string[] {
  if (Array.isArray(details)) return reasonsOf(details);
  if (details && typeof details === "object")
    return reasonsOf((details as Record<string, unknown>).blocking_reasons);
  return [];
}

export function useScheduleTerms(opts: Options) {
  const { session, setSession } = useAuth();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [committing, setCommitting] = useState(false);
  // null = untouched: the field follows the gross total of the previewed terms.
  const [ceilingInput, setCeilingInput] = useState<string | null>(
    opts.initialCeiling ?? null,
  );
  const latest = useRef(opts);
  latest.current = opts;
  const request = useRef(0);

  const current: Outcome =
    outcome && outcome.forKey === opts.inputsKey
      ? outcome
      : outcomeFor(opts.inputsKey);
  const terms = current.terms;
  const ceiling = ceilingInput ?? terms?.gross_total ?? "";
  const currencyCode = terms?.currency ?? "EUR";
  const clientCeilingError = terms
    ? ceilingError(ceiling, terms.gross_total, (v) => currency(v, currencyCode))
    : "";
  const notReady = terms != null && terms.policy_outcome !== "ready_to_commit";
  const blocking = [
    ...reasonsOf(terms?.blocking_reasons),
    ...current.blocking.filter(
      (r) => !reasonsOf(terms?.blocking_reasons).includes(r),
    ),
  ];

  // Maps a failed call to what the screen shows. 401 is the session expiring.
  const failure = useCallback(
    (forKey: string, e: unknown, keep?: Outcome): Outcome | null => {
      const base = keep ?? outcomeFor(forKey);
      if (!(e instanceof ApiError))
        return {
          ...base,
          error: "The service could not be reached. Try again.",
        };
      switch (e.code) {
        case "SCHEDULE_CEILING_TOO_LOW":
          return { ...base, ceilingError: e.message };
        case "SCHEDULE_NOT_REORDERABLE":
          return {
            ...base,
            error: e.message,
            blocking: reasonsFromDetails(e.details),
            refused: true,
          };
        case "SCHEDULE_LIMIT":
          return { ...base, error: LIMIT_TEXT };
        case "NOT_FOUND":
          return { ...base, notFound: true };
        default:
          return { ...base, error: e.message };
      }
    },
    [],
  );

  const runPreview = useCallback(
    async (notice = "") => {
      if (!session) return;
      const forKey = latest.current.inputsKey;
      const mine = ++request.current;
      setPreviewing(true);
      try {
        const next = await latest.current.preview(session.csrf_token);
        if (mine !== request.current) return;
        latest.current.onTerms?.(next);
        setOutcome(
          outcomeFor(forKey, {
            terms: next,
            // A key belongs to one preview of the terms; the customer's next preview gets another.
            idempotencyKey: newIdempotencyKey(),
            notice,
          }),
        );
      } catch (e) {
        if (mine !== request.current) return;
        if (e instanceof ApiError && e.status === 401) setSession(null);
        else setOutcome(failure(forKey, e, outcomeFor(forKey, { notice })));
      } finally {
        if (mine === request.current) setPreviewing(false);
      }
    },
    [failure, session, setSession],
  );

  const previewTerms = useCallback(() => runPreview(), [runPreview]);

  const setAgreed = (agreed: boolean) =>
    setOutcome({ ...current, agreed, error: "" });

  const submit = async () => {
    if (!session || !terms || !current.idempotencyKey || committing) return;
    if (clientCeilingError || notReady || current.refused) return;
    const forKey = opts.inputsKey;
    const sent = current;
    setCommitting(true);
    setOutcome({ ...sent, error: "", ceilingError: "", notice: "" });
    try {
      const schedule = await latest.current.commit(session.csrf_token, {
        fingerprint: terms.terms_fingerprint,
        key: current.idempotencyKey,
        ceiling: formatCeiling(ceiling),
      });
      latest.current.onDone(schedule);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setSession(null);
        return;
      }
      const code = e instanceof ApiError ? e.code : undefined;
      if (code === "SCHEDULE_TERMS_CHANGED") {
        // The prices moved after the preview: show the new terms and ask for the agreement again.
        setCommitting(false);
        setOutcome(outcomeFor(forKey, { notice: TERMS_CHANGED_NOTICE }));
        await runPreview(TERMS_CHANGED_NOTICE);
        return;
      }
      if (code === "IDEMPOTENCY_CONFLICT") {
        setOutcome({
          ...sent,
          idempotencyKey: newIdempotencyKey(),
          agreed: false,
          error:
            "That submission was already used for different terms. Review the terms and submit again.",
        });
      } else if (code === "SCHEDULE_NOT_ACTIVE") {
        latest.current.onNotActive?.();
        setOutcome({ ...sent, error: e instanceof ApiError ? e.message : "" });
      } else {
        setOutcome(failure(forKey, e, { ...sent, error: "" }));
      }
    } finally {
      setCommitting(false);
    }
  };

  return {
    terms,
    // Terms were previewed, but the form has changed since.
    stale: terms == null && outcome?.terms != null,
    previewing,
    committing,
    previewTerms,
    submit,
    notice: current.notice,
    error: current.error,
    notFound: current.notFound,
    blocking,
    notReady,
    refused: current.refused,
    agreed: current.agreed,
    setAgreed,
    ceiling,
    setCeiling: setCeilingInput,
    ceilingError: clientCeilingError || current.ceilingError,
    clientCeilingError,
    canSubmit:
      terms != null &&
      !notReady &&
      !current.refused &&
      current.agreed &&
      !clientCeilingError &&
      !committing,
  };
}
