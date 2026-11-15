import { useId } from "react";
import type { Proposal } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { useCartEdit } from "../hooks/useCartEdit";
import { EDIT_COPY } from "../model/cartEdit";
import { GhostLine } from "./GhostLine";
import { QuantityControl } from "./QuantityControl";

/**
 * The lines of the prepared basket with a number control per product and the 15 second ghost for a
 * line set to 0. `editable` and `reason` come from the conversation (`cart_editable`, `cart_edit_reason`);
 * the controls are disabled with that reason, and while the assistant is working.
 */
export function CartLines({
  p,
  conversationId,
  editable,
  reason,
  working,
  onUpdated,
}: {
  p: Proposal;
  conversationId: string;
  editable: boolean;
  reason: string | null;
  working: boolean;
  onUpdated?: (proposal: Proposal) => void;
}) {
  const edit = useCartEdit({ conversationId, proposal: p, onUpdated });
  const reasonId = useId();
  const disabled = !editable || working;
  const why = !editable ? reason : working ? EDIT_COPY.working : null;
  const message = edit.error || (edit.invalid.length ? EDIT_COPY.invalid : "");
  return (
    <div className="flex flex-col gap-space-sm">
      <span className="font-label text-label-sm font-bold uppercase tracking-wider text-secondary">
        Ingredients &amp; staged items
      </span>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 font-body text-body-sm text-on-surface">
        {edit.rows.map((row) =>
          row.kind === "ghost" ? (
            <GhostLine
              key={row.id}
              id={row.id}
              removed={row.removed}
              disabled={disabled}
              describedBy={why ? reasonId : undefined}
              onRestore={() => edit.restore(row.id)}
              onText={(text) => edit.setText(row.id, text)}
            />
          ) : (
            <li
              key={row.id}
              data-testid="cart-line"
              data-product-id={row.id}
              className="flex items-center justify-between gap-space-sm border-b border-border-subtle/50 py-1"
            >
              <span className="min-w-0 break-words">{row.name}</span>
              <div className="flex shrink-0 flex-col items-end gap-1 text-right font-mono text-primary">
                {row.server === null ? (
                  <span className="font-bold">Unresolved {row.salesUnit}</span>
                ) : (
                  <span className="inline-flex items-center gap-1">
                    <QuantityControl
                      name={row.name}
                      text={row.text}
                      server={row.server}
                      disabled={disabled}
                      invalid={edit.flagged.has(row.id)}
                      describedBy={why ? reasonId : undefined}
                      onText={(text) => edit.setText(row.id, text)}
                      onSave={() => edit.setText(row.id, row.text, true)}
                      onLeave={() => edit.settle(row.id)}
                    />
                    <span className="text-label-sm">{row.salesUnit}</span>
                  </span>
                )}
                {row.line && (
                  <span className="text-label-sm">
                    {currency(row.line.gross, p.snapshot.currency ?? "EUR")}
                  </span>
                )}
              </div>
            </li>
          ),
        )}
      </ul>
      {edit.updating && (
        <span
          role="status"
          data-testid="cart-updating"
          className="text-label-sm text-secondary"
        >
          {EDIT_COPY.updating}
        </span>
      )}
      {why && (
        <p
          id={reasonId}
          data-testid="cart-edit-reason"
          className="m-0 text-label-sm text-on-surface-variant"
        >
          {why}
        </p>
      )}
      <ErrorMessage message={message} debug={edit.errorDebug} />
      {edit.error && (
        <button
          type="button"
          onClick={edit.retry}
          className="cursor-pointer self-start rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary"
        >
          {EDIT_COPY.tryAgain}
        </button>
      )}
      <p
        role="status"
        aria-live="polite"
        data-testid="cart-live-note"
        className="sr-only"
      >
        {edit.note}
      </p>
    </div>
  );
}
