import { title } from "../lib/format";

const tones: Record<string, string> = {
  pending: "bg-amber-100 text-amber-900",
  approval_required: "bg-amber-100 text-amber-900",
  approved: "bg-green-100 text-green-900",
  accepted_mock: "bg-green-100 text-green-900",
  ready_to_commit: "bg-green-100 text-green-900",
  rejected: "bg-error-container text-on-error-container",
  denied: "bg-error-container text-on-error-container",
  expired: "bg-surface-container-high text-on-surface-variant",
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
