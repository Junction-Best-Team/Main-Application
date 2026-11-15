import { useId } from "react";
import { Link } from "react-router-dom";
import type { Proposal } from "../../../shared/api/types";
import type { ErrorDebug } from "../../../shared/api/client";
import { Badge } from "../../../shared/components/Badge";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { currency } from "../../../shared/lib/format";
import { useCardLog } from "../model/cardLog";
import { blockerOf } from "../model/cardState";
import { CART_COPY } from "../model/cartCopy";
import { EDIT_COPY } from "../model/cartEdit";
import { getPurchaseStatus } from "../model/purchaseStatus";
import { DisabledConfirm } from "./DisabledConfirm";
import { useVatBreakdown } from "../hooks/useVatBreakdown";
import { VatButton, VatDetails } from "./VatBreakdown";

type Problem = { message: string; debug?: ErrorDebug };

/**
 * The part of the card that is always in view under the tabs: the total, the status chip (only when
 * the order is not ready), the Confirm purchase button with the one line that says why it is grey,
 * the status line, the errors (with Try again for a failed edit) and Reject for an approver.
 */
export function CardFooter({
  p,
  canConfirm,
  busy,
  working,
  updating,
  message,
  problems,
  onRetry,
  confirm,
  reject,
}: {
  p: Proposal;
  canConfirm: boolean;
  busy: boolean;
  /** The assistant is working on the conversation: the button is grey with that reason. */
  working: boolean;
  /** A new proposal is loading after an edit. */
  updating: boolean;
  /** The status line ("Terms changed during verification..."). */
  message: string;
  problems: Problem[];
  /** Re-sends a failed edit with the same request id; undefined when the failure is not an edit. */
  onRetry?: () => void;
  confirm: () => Promise<void>;
  reject: () => Promise<void>;
}) {
  const reasonId = useId();
  const vat = useVatBreakdown(p);
  const status = getPurchaseStatus(p);
  const blocker = blockerOf(p);
  const grey = updating || !canConfirm;
  useCardLog({
    kind: "button",
    component: "prepared",
    enabled: !grey && !busy && !working,
    reason: updating
      ? "updating"
      : !canConfirm
        ? blocker.code
        : working
          ? "assistant working"
          : busy
            ? "verifying"
            : "none",
  });
  return (
    <div
      data-testid="card-footer"
      className="flex shrink-0 flex-col gap-space-xs border-t border-border-subtle pt-space-sm"
    >
      <div
        data-testid="card-total-row"
        className="flex items-center justify-between gap-space-sm"
      >
        <div className="flex items-baseline gap-space-sm">
          <span className="font-label text-label-md font-bold text-on-surface-variant">
            Total
          </span>
          <strong className="font-mono font-label text-headline-sm text-primary">
            {currency(p.snapshot.gross_total, p.snapshot.currency ?? "EUR")}
          </strong>
        </div>
        <div className="flex items-center gap-space-xs">
          {status !== "ready_to_commit" && (
            <span data-testid="card-status-chip">
              <Badge value={status} />
            </span>
          )}
          <VatButton state={vat} />
        </div>
      </div>
      <VatDetails p={p} state={vat} />
      {message && (
        <p
          role="status"
          data-testid="card-status"
          className="m-0 rounded-lg border border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950/50 px-3 py-2 text-body-sm text-green-900 dark:text-green-100"
        >
          {message}
        </p>
      )}
      {problems.map((problem, i) => (
        <ErrorMessage key={i} message={problem.message} debug={problem.debug} />
      ))}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="cursor-pointer self-start rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary"
        >
          {EDIT_COPY.tryAgain}
        </button>
      )}
      {grey ? (
        <DisabledConfirm
          component="prepared"
          code={updating ? "updating" : blocker.code}
          reason={updating ? CART_COPY.updatingOrder : blocker.text}
          log={false}
        />
      ) : (
        <>
          <button
            type="button"
            className="primary full block w-full rounded border border-status-fresh-green bg-status-fresh-green px-4 py-3 font-label text-label-lg font-bold text-deep-ocean-navy hover:enabled:bg-tertiary-fixed disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy || working}
            aria-describedby={working ? reasonId : undefined}
            onClick={confirm}
          >
            {busy ? "Verifying purchase…" : CART_COPY.button}
          </button>
          {working && (
            <p
              id={reasonId}
              data-testid="card-reason"
              className="m-0 text-label-sm text-on-surface-variant"
            >
              {CART_COPY.working}
            </p>
          )}
          {p.can_decide && status === "pending" && (
            <button
              type="button"
              className="danger full block w-full rounded border border-error bg-transparent px-4 py-2 font-label text-label-md font-bold text-error hover:enabled:bg-error-container"
              disabled={busy}
              onClick={reject}
            >
              Reject
            </button>
          )}
        </>
      )}
      {p.order_id && (
        <>
          <p className="m-0 text-body-sm text-secondary">
            Order accepted. No real supplier order was placed.
          </p>
          <p className="order-reference m-0 font-label font-bold text-primary wrap-anywhere">
            Order {p.order_id}
          </p>
        </>
      )}
      {status === "superseded" && (
        <Link
          to={`/purchases/${p.proposal_id}`}
          className="font-label text-label-md"
        >
          View current revision {p.current_revision}
        </Link>
      )}
    </div>
  );
}
