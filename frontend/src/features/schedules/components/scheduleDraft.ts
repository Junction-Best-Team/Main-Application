import { formatDate } from "../model/scheduleStatus";
import type {
  LineRule,
  Recurrence,
  ScheduleLine,
} from "../../../shared/api/types";

// Pure helpers for the create and edit forms: the recurrence the customer picks, the per-line
// rules and the price ceiling. The server owns the real validation; these only avoid a round
// trip for mistakes the form can see.

export type Preset = "weekly" | "twice" | "biweekly" | "every4" | "custom";
export type CustomMode = "weekdays" | "days";
export type RecurrenceDraft = {
  preset: Preset;
  /** Weekdays of "twice a week" and of custom weekdays; 0 = Monday ... 6 = Sunday. */
  weekdays: number[];
  customMode: CustomMode;
  /** Text so the customer can clear the field while typing. */
  everyWeeks: string;
  everyDays: string;
};

export const PRESETS: { value: Preset; label: string }[] = [
  { value: "weekly", label: "Weekly" },
  { value: "twice", label: "Twice a week" },
  { value: "biweekly", label: "Every other week" },
  { value: "every4", label: "Every 4 days" },
  { value: "custom", label: "Custom" },
];
export const WEEKDAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

export const DEFAULT_DRAFT: RecurrenceDraft = {
  preset: "weekly",
  weekdays: [],
  customMode: "weekdays",
  everyWeeks: "1",
  everyDays: "7",
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;

// 0 = Monday ... 6 = Sunday for a plain calendar date. Never goes through a local time zone.
export function weekdayOf(isoDate: string): number | null {
  if (!DATE.test(isoDate)) return null;
  const day = new Date(`${isoDate}T00:00:00Z`).getUTCDay();
  return Number.isNaN(day) ? null : (day + 6) % 7;
}

// Today as a Helsinki calendar date, the zone the server schedules in.
export function todayHelsinki(offsetDays = 0): string {
  const now = new Date(Date.now() + offsetDays * 86_400_000);
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Helsinki",
  }).format(now);
}

// The first run date must be tomorrow or later and at most 365 days ahead (owner Q-103); demo
// mode may allow today. Both limits are Helsinki calendar dates.
export const firstRunRange = (allowToday = false) => ({
  min: todayHelsinki(allowToday ? 0 : 1),
  max: todayHelsinki(365),
});

export function validateDate(isoDate: string, allowToday = false): string {
  if (!DATE.test(isoDate) || weekdayOf(isoDate) === null)
    return "Choose the first run date.";
  const { min, max } = firstRunRange(allowToday);
  if (isoDate < min || isoDate > max)
    return `The first run date must be from ${formatDate(min)} to ${formatDate(max)}.`;
  return "";
}

const wholeNumber = (text: string, min: number, max: number) =>
  /^\d{1,3}$/.test(text.trim()) && Number(text) >= min && Number(text) <= max;

/** The Recurrence JSON the server expects, or the reason it cannot be built yet. */
export function buildRecurrence(
  draft: RecurrenceDraft,
  firstRunDate: string,
): { recurrence: Recurrence | null; error: string } {
  const first = weekdayOf(firstRunDate);
  const invalid = (error: string) => ({ recurrence: null, error });
  switch (draft.preset) {
    case "weekly":
      return first === null
        ? invalid("")
        : {
            recurrence: { kind: "weekdays", weekdays: [first], every_weeks: 1 },
            error: "",
          };
    case "biweekly":
      return first === null
        ? invalid("")
        : {
            recurrence: { kind: "weekdays", weekdays: [first], every_weeks: 2 },
            error: "",
          };
    case "twice": {
      const days = [...new Set(draft.weekdays)].sort((a, b) => a - b);
      return days.length === 2
        ? {
            recurrence: { kind: "weekdays", weekdays: days, every_weeks: 1 },
            error: "",
          }
        : invalid("Choose exactly two weekdays.");
    }
    case "every4":
      return {
        recurrence: { kind: "days", interval: 4, every_weeks: 1 },
        error: "",
      };
    case "custom":
      if (draft.customMode === "days") {
        return wholeNumber(draft.everyDays, 1, 365)
          ? {
              recurrence: {
                kind: "days",
                interval: Number(draft.everyDays),
                every_weeks: 1,
              },
              error: "",
            }
          : invalid("Enter a whole number from 1 to 365.");
      } else {
        const days = [...new Set(draft.weekdays)].sort((a, b) => a - b);
        if (days.length === 0) return invalid("Choose at least one weekday.");
        if (!wholeNumber(draft.everyWeeks, 1, 52))
          return invalid("Enter a whole number of weeks from 1 to 52.");
        return {
          recurrence: {
            kind: "weekdays",
            weekdays: days,
            every_weeks: Number(draft.everyWeeks),
          },
          error: "",
        };
      }
  }
}

/** Reads a saved Recurrence back into the picker (the edit page). */
export function draftFromRecurrence(
  r: Recurrence,
  firstRunDate: string,
): RecurrenceDraft {
  const weeks = r.every_weeks ?? 1;
  if (r.kind === "days") {
    const interval = r.interval ?? 1;
    return interval === 4 && weeks === 1
      ? { ...DEFAULT_DRAFT, preset: "every4" }
      : {
          ...DEFAULT_DRAFT,
          preset: "custom",
          customMode: "days",
          everyDays: String(interval),
        };
  }
  const days = [...(r.weekdays ?? [])].sort((a, b) => a - b);
  const first = weekdayOf(firstRunDate);
  const single = days.length === 1 && days[0] === first;
  if (single && weeks === 1) return { ...DEFAULT_DRAFT, preset: "weekly" };
  if (single && weeks === 2) return { ...DEFAULT_DRAFT, preset: "biweekly" };
  if (days.length === 2 && weeks === 1)
    return { ...DEFAULT_DRAFT, preset: "twice", weekdays: days };
  return {
    ...DEFAULT_DRAFT,
    preset: "custom",
    customMode: "weekdays",
    weekdays: days,
    everyWeeks: String(weeks),
  };
}

// ---- line rules ----------------------------------------------------------------------------

export type RuleDraft = { substitutes: string[]; pct: string };
export type RuleDrafts = Record<string, RuleDraft>;
export const MAX_SUBSTITUTES = 5;

/** What a line already carries (the server resolved it), as an editable draft. */
export const ruleFromLine = (line: ScheduleLine): RuleDraft => ({
  substitutes: (line.accepted_substitutes ?? []).map((s) => s.product_id),
  pct: line.price_range_pct ?? "0.00",
});
export const rulesFromLines = (lines: ScheduleLine[]): RuleDrafts =>
  Object.fromEntries(lines.map((l) => [l.product_id, ruleFromLine(l)]));

const PCT = /^\d{1,3}([.,]\d{1,2})?$/;
export function validatePct(text: string): string {
  const t = text.trim();
  if (t === "") return "";
  const ok = PCT.test(t) && Number(t.replace(",", ".")) <= 100;
  return ok ? "" : "Enter a percentage from 0 to 100 with up to 2 decimals.";
}
/** "7,5" and "" become "7.50" and "0.00". */
export const formatPct = (text: string) =>
  (Number(text.trim().replace(",", ".")) || 0).toFixed(2);

export function ruleErrors(rules: RuleDrafts): boolean {
  return Object.values(rules).some((r) => validatePct(r.pct) !== "");
}

/** The `line_rules` object of the requests: keyed by product id, decimal strings. */
export function buildLineRules(rules: RuleDrafts): Record<string, LineRule> {
  return Object.fromEntries(
    Object.entries(rules).map(([productId, r]) => [
      productId,
      {
        accepted_substitutes: [...r.substitutes],
        price_range_pct: formatPct(r.pct),
      },
    ]),
  );
}

// ---- price ceiling -------------------------------------------------------------------------

const MONEY = /^\d+([.,]\d{1,2})?$/;
const cents = (text: string) =>
  Math.round(Number(text.replace(",", ".")) * 100);

export function ceilingError(
  text: string,
  grossTotal: string | null,
  formatMoney: (value: string) => string,
): string {
  const t = text.trim();
  if (!MONEY.test(t)) return "Enter an amount with up to 2 decimals.";
  if (grossTotal != null && cents(t) < cents(grossTotal))
    return `The ceiling must be at least the total of ${formatMoney(grossTotal)}.`;
  return "";
}
export const formatCeiling = (text: string) =>
  (cents(text.trim()) / 100).toFixed(2);
