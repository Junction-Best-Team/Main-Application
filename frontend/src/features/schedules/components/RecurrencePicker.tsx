import {
  PRESETS,
  WEEKDAY_NAMES,
  buildRecurrence,
  validateDate,
  weekdayOf,
  type RecurrenceDraft,
} from "./scheduleDraft";
import { errorText, field, hint, label } from "./formStyles";

type Props = {
  draft: RecurrenceDraft;
  onDraft: (draft: RecurrenceDraft) => void;
  firstRunDate: string;
  onFirstRunDate: (isoDate: string) => void;
  minDate: string;
};

const radioRow =
  "flex min-h-11 cursor-pointer items-center gap-space-sm rounded-lg border border-border-subtle px-space-md py-2 font-body text-body-md has-[:checked]:border-wholesale-teal has-[:checked]:bg-surface-container-low";
const group = "m-0 flex min-w-0 flex-col gap-space-xs border-0 p-0";

export function RecurrencePicker({
  draft,
  onDraft,
  firstRunDate,
  onFirstRunDate,
  minDate,
}: Props) {
  const set = (patch: Partial<RecurrenceDraft>) =>
    onDraft({ ...draft, ...patch });
  const toggleDay = (day: number) =>
    set({
      weekdays: draft.weekdays.includes(day)
        ? draft.weekdays.filter((d) => d !== day)
        : [...draft.weekdays, day],
    });
  const dateError = validateDate(firstRunDate);
  const recurrenceError = buildRecurrence(draft, firstRunDate).error;
  const weekday = weekdayOf(firstRunDate);
  const showDays =
    draft.preset === "twice" ||
    (draft.preset === "custom" && draft.customMode === "weekdays");
  const dayName =
    weekday === null ? "the weekday of the first run" : WEEKDAY_NAMES[weekday];
  const presetHint: Partial<Record<typeof draft.preset, string>> = {
    weekly: `Every week on ${dayName}.`,
    biweekly: `Every second week on ${dayName}.`,
    every4: "A run every 4 days, counted from the first run date.",
  };
  return (
    <div className="flex flex-col gap-space-md">
      <label className="flex flex-col gap-1">
        <span className={label}>First run date</span>
        <input
          type="date"
          className={field}
          value={firstRunDate}
          min={minDate}
          aria-invalid={dateError ? "true" : undefined}
          onChange={(e) => onFirstRunDate(e.target.value)}
        />
        {dateError && <span className={errorText}>{dateError}</span>}
      </label>

      <fieldset className={group}>
        <legend className={`${label} mb-1 p-0`}>Repeat</legend>
        <div className="grid grid-cols-1 gap-space-xs sm:grid-cols-2">
          {PRESETS.map((p) => (
            <label key={p.value} className={radioRow}>
              <input
                type="radio"
                name="recurrence-preset"
                checked={draft.preset === p.value}
                onChange={() => set({ preset: p.value })}
              />
              {p.label}
            </label>
          ))}
        </div>
        {presetHint[draft.preset] && (
          <p className={hint}>{presetHint[draft.preset]}</p>
        )}
      </fieldset>

      {draft.preset === "custom" && (
        <fieldset className={group}>
          <legend className={`${label} mb-1 p-0`}>Custom pattern</legend>
          <div className="grid grid-cols-1 gap-space-xs sm:grid-cols-2">
            <label className={radioRow}>
              <input
                type="radio"
                name="custom-mode"
                checked={draft.customMode === "weekdays"}
                onChange={() => set({ customMode: "weekdays" })}
              />
              Days of the week
            </label>
            <label className={radioRow}>
              <input
                type="radio"
                name="custom-mode"
                checked={draft.customMode === "days"}
                onChange={() => set({ customMode: "days" })}
              />
              Every few days
            </label>
          </div>
        </fieldset>
      )}

      {showDays && (
        <fieldset className={group}>
          <legend className={`${label} mb-1 p-0`}>Weekdays</legend>
          <div className="flex flex-wrap gap-space-xs">
            {WEEKDAY_NAMES.map((name, day) => (
              <label key={name} className={`${radioRow} grow basis-[7.5rem]`}>
                <input
                  type="checkbox"
                  checked={draft.weekdays.includes(day)}
                  onChange={() => toggleDay(day)}
                />
                {name}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {draft.preset === "custom" && draft.customMode === "weekdays" && (
        <label className="flex max-w-48 flex-col gap-1">
          <span className={label}>Repeat every (weeks)</span>
          <input
            className={field}
            inputMode="numeric"
            value={draft.everyWeeks}
            onChange={(e) => set({ everyWeeks: e.target.value })}
          />
        </label>
      )}
      {draft.preset === "custom" && draft.customMode === "days" && (
        <label className="flex max-w-48 flex-col gap-1">
          <span className={label}>Repeat every (days)</span>
          <input
            className={field}
            inputMode="numeric"
            value={draft.everyDays}
            onChange={(e) => set({ everyDays: e.target.value })}
          />
        </label>
      )}
      {recurrenceError && <p className={errorText}>{recurrenceError}</p>}
    </div>
  );
}
