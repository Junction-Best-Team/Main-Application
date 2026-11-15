import { Icon } from "../../../shared/components/DesignPrimitives";
import { CART_EDIT, EDIT_COPY, parseQuantity } from "../model/cartEdit";

const stepButton =
  "flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-outline-variant bg-surface-pure p-0 text-primary disabled:cursor-not-allowed disabled:opacity-40";

/**
 * The number of packs of one product: a number input with minus and plus. Typing is never blocked;
 * the caller debounces the save. Keyboard: arrow keys change the number, Enter saves at once.
 */
export function QuantityControl({
  name,
  text,
  server,
  disabled,
  invalid,
  describedBy,
  onText,
  onSave,
  onLeave,
}: {
  name: string;
  /** What the input shows (typed text, or the server's number). */
  text: string;
  /** The server's number, the fallback for minus and plus when the text is not a number. */
  server: number;
  disabled: boolean;
  invalid: boolean;
  describedBy?: string;
  onText: (text: string) => void;
  /** Enter was pressed: save now. */
  onSave: () => void;
  onLeave: () => void;
}) {
  const value = parseQuantity(text);
  const current = value ?? server;
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        aria-label={EDIT_COPY.decrease(name)}
        disabled={disabled || current <= CART_EDIT.min}
        onClick={() => onText(String(Math.max(CART_EDIT.min, current - 1)))}
        className={stepButton}
      >
        <Icon name="remove" />
      </button>
      <input
        type="number"
        inputMode="numeric"
        aria-label={EDIT_COPY.quantityOf(name)}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        min={CART_EDIT.min}
        max={CART_EDIT.max}
        step={1}
        value={text}
        disabled={disabled}
        onChange={(e) => onText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onSave();
          }
        }}
        onBlur={onLeave}
        className={`h-9 w-16 rounded-lg border bg-surface-pure px-1 text-center font-mono text-body-sm text-primary disabled:cursor-not-allowed disabled:opacity-60 ${invalid ? "border-error" : "border-outline-variant"}`}
      />
      <button
        type="button"
        aria-label={EDIT_COPY.increase(name)}
        disabled={disabled || current >= CART_EDIT.max}
        onClick={() => onText(String(Math.min(CART_EDIT.max, current + 1)))}
        className={stepButton}
      >
        <Icon name="add" />
      </button>
    </span>
  );
}
