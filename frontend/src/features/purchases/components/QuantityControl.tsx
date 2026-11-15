import { Icon } from "../../../shared/components/DesignPrimitives";
import { CART_EDIT, EDIT_COPY, parseQuantity } from "../model/cartEdit";

// A thin caret above and one below the number. They are invisible until the row is hovered or a
// control inside it has the keyboard focus, and faint all the time on touch screens (no hover).
const caret =
  "flex h-4 w-10 cursor-pointer items-center justify-center rounded border-0 bg-transparent p-0 text-secondary opacity-0 transition-opacity group-hover/qty:opacity-100 focus-visible:opacity-100 group-focus-within/qty:opacity-100 [@media(hover:none)]:opacity-40 disabled:cursor-not-allowed disabled:opacity-0 [@media(hover:none)]:disabled:opacity-20";

/**
 * The number of packs of one product. The number is a real spinbutton (role, name "Quantity of
 * <product>", min 0, max 100000, arrow keys, Enter saves, click it and type); the carets above and
 * below are decoration with their own buttons. Typing is never blocked; the caller debounces the save.
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
  /** The server's number, the fallback for the carets when the text is not a number. */
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
    <span className="group/qty inline-flex flex-col items-center">
      <button
        type="button"
        aria-label={EDIT_COPY.increase(name)}
        disabled={disabled || current >= CART_EDIT.max}
        onClick={() => onText(String(Math.min(CART_EDIT.max, current + 1)))}
        className={caret}
      >
        <Icon name="keyboard_arrow_up" />
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
        className={`h-7 w-14 rounded-md border bg-transparent px-1 text-center font-mono text-body-sm text-primary [appearance:textfield] focus:bg-surface-container-low focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none ${invalid ? "border-error" : "border-transparent focus:border-outline-variant"}`}
      />
      <button
        type="button"
        aria-label={EDIT_COPY.decrease(name)}
        disabled={disabled || current <= CART_EDIT.min}
        onClick={() => onText(String(Math.max(CART_EDIT.min, current - 1)))}
        className={caret}
      >
        <Icon name="keyboard_arrow_down" />
      </button>
    </span>
  );
}
