import type { Schedule } from "../../../shared/api/types";
import { scheduleChip, type ChipTone } from "../model/scheduleStatus";

// Just the word in its colour, like the status on the Orders page (no pill).
const toneClass: Record<ChipTone, string> = {
  positive: "text-green-700 dark:text-green-300",
  attention: "text-amber-700 dark:text-amber-300",
  neutral: "text-secondary",
  negative: "text-error",
};

export function ToneChip({ label, tone }: { label: string; tone: ChipTone }) {
  return (
    <span
      className={`inline-flex h-[26px] items-center font-label text-label-sm font-bold whitespace-nowrap ${toneClass[tone]}`}
    >
      {label}
    </span>
  );
}

export function ScheduleChip({
  schedule,
}: {
  schedule: Pick<Schedule, "status" | "next_run_date">;
}) {
  const chip = scheduleChip(schedule);
  return <ToneChip label={chip.label} tone={chip.tone} />;
}
