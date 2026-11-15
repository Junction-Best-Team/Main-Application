import { useId } from "react";
import { useCardLog } from "../model/cardLog";
import { CART_COPY } from "../model/cartCopy";

/**
 * The purchase button when it cannot be pressed: always on the card, greyed, with the reason as text
 * and as its accessible description (so the customer never wonders where the button went).
 */
export function DisabledConfirm({
  reason,
  code,
  component,
  log = true,
}: {
  reason: string;
  /** Short state name for the debug log, for example "order placed". */
  code: string;
  component: string;
  /** False when the caller already logs the button decision. */
  log?: boolean;
}) {
  const reasonId = useId();
  useCardLog(
    log ? { kind: "button", component, enabled: false, reason: code } : null,
  );
  return (
    <div className="flex flex-col gap-space-xs">
      <button
        type="button"
        disabled
        aria-describedby={reasonId}
        className="cursor-not-allowed rounded-lg border-0 bg-surface-container-high px-space-md py-3 font-label text-label-lg font-bold text-on-surface-variant"
      >
        {CART_COPY.button}
      </button>
      <p
        id={reasonId}
        data-testid="card-reason"
        className="m-0 text-label-sm text-on-surface-variant"
      >
        {reason}
      </p>
    </div>
  );
}
