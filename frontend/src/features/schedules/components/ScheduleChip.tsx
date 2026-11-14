import type { Schedule } from "../../../shared/api/types";
import { scheduleChip, type ChipTone } from "../model/scheduleStatus";

// Same pill look and token classes as shared/components/Badge, driven by the schedule chip tone.
const toneClass: Record<ChipTone, string> = {
  positive: "bg-green-100 text-green-900",
  attention: "bg-amber-100 text-amber-900",
  neutral: "bg-surface-container-high text-on-surface-variant",
  negative: "bg-error-container text-on-error-container",
};

export function ToneChip({ label, tone }: { label: string; tone: ChipTone }) {
  return (
    <span
      className={`inline-block rounded-full px-3 py-1.5 font-label text-label-sm font-bold whitespace-nowrap ${toneClass[tone]}`}
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
