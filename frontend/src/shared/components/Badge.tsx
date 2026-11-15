import { title } from "../lib/format";

const tones: Record<string, string> = {
  pending:
    "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100",
  approval_required:
    "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100",
  approved:
    "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-100",
  accepted_mock:
    "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-100",
  ready_to_commit:
    "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-100",
  rejected: "bg-error-container text-on-error-container",
  denied: "bg-error-container text-on-error-container",
  expired: "bg-surface-container-high text-on-surface-variant",
  scheduled:
    "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-100",
  active:
    "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-100",
  placed:
    "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-100",
  paused: "bg-surface-container-high text-on-surface-variant",
  cancelled: "bg-surface-container-high text-on-surface-variant",
  superseded: "bg-surface-container-high text-on-surface-variant",
  stopped:
    "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100",
  disrupted:
    "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100",
  committed:
    "bg-green-100 text-green-900 dark:bg-green-900/40 dark:text-green-100",
  skipped: "bg-surface-container-high text-on-surface-variant",
};

export function Badge({ value }: { value: string }) {
  return (
    <span
      className={`badge ${value} inline-block rounded-full px-3 py-1.5 font-label text-label-sm font-bold whitespace-nowrap ${tones[value] ?? "bg-surface-container-high text-on-surface-variant"}`}
    >
      {title(value)}
    </span>
  );
}
