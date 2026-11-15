import { EDIT_COPY } from "../model/cartEdit";
import type { Removed } from "../hooks/useCartEdit";
import { QuantityControl } from "./QuantityControl";

/**
 * A line the customer set to 0, kept for a few seconds: greyed, still clickable (a click puts it back).
 * It is a client-side copy; the server basket already excludes the line.
 */
export function GhostLine({
  id,
  removed,
  disabled,
  describedBy,
  onRestore,
  onText,
}: {
  id: string;
  removed: Removed;
  disabled: boolean;
  describedBy?: string;
  onRestore: () => void;
  onText: (text: string) => void;
}) {
  return (
    <li
      data-testid="ghost-line"
      data-product-id={id}
      data-state={removed.phase}
      className={`flex items-center justify-between gap-space-sm border-b border-border-subtle/50 py-1 transition-opacity duration-300 motion-reduce:transition-none ${removed.phase === "fading" ? "opacity-0" : "opacity-50"}`}
    >
      <button
        type="button"
        aria-label={EDIT_COPY.putBack(removed.name)}
        disabled={disabled}
        onClick={onRestore}
        className="min-w-0 cursor-pointer break-words border-0 bg-transparent p-0 text-left font-body text-body-sm text-on-surface"
      >
        <span className="block line-through">{removed.name}</span>
        <span className="block text-label-sm text-secondary">
          {EDIT_COPY.was(removed.lastQuantity, removed.salesUnit)}
        </span>
      </button>
      <QuantityControl
        name={removed.name}
        text="0"
        server={0}
        disabled={disabled}
        invalid={false}
        describedBy={describedBy}
        onText={onText}
        onSave={onRestore}
        onLeave={() => undefined}
      />
    </li>
  );
}
