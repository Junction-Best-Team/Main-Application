import { Link } from "react-router-dom";
import type { Proposal } from "../../../shared/api/types";
import { currency, title } from "../../../shared/lib/format";
import {
  CHECK_GROUPS,
  EXPIRED_GROUP,
  groupChecks,
  outcomeBlocks,
} from "../model/checkClasses";
import { getPurchaseStatus } from "../model/purchaseStatus";

const groupClass =
  "flex flex-col gap-space-xs rounded-lg border border-border-subtle p-space-sm";

/**
 * The Checks tab: the purchasing checks in groups by what the customer can do (blockers first, then
 * approvals, then warnings), each with a short text and a "what you can do" line, and a Refresh button when
 * the approval expired. The code stays as a small label. `onRefresh` is one handler so the server refresh
 * route can replace the plain reload later.
 */
export function PurchaseChecks({
  p,
  onRefresh,
}: {
  p: Proposal;
  onRefresh?: () => void | Promise<void>;
}) {
  const status = getPurchaseStatus(p);
  const groups = groupChecks(p);
  const expired = status === "expired" && !p.order_id;
  const showExpired = expired || groups.expired.length > 0;
  return (
    <section className="decision-panel flex flex-col gap-space-sm [&_h3]:font-label [&_h3]:text-label-md [&_h3]:text-secondary">
      <h3 className="m-0">Purchasing checks</h3>
      {CHECK_GROUPS.map(({ cls, heading, action }) => {
        const items = groups[cls];
        const show =
          items.length > 0 || (cls === "blocker" && outcomeBlocks(p));
        if (!show) return null;
        return (
          <div
            key={cls}
            role="group"
            aria-label={heading}
            data-class={cls}
            className={groupClass}
          >
            <h4 className="m-0 font-label text-label-md font-bold text-primary">
              {heading}
            </h4>
            {items.length > 0 && (
              <ul className="m-0 list-none space-y-2 p-0 text-body-sm">
                {items.map((item, i) => (
                  <li key={i}>
                    {item.product ? `${item.product}: ` : ""}
                    {item.text}
                    <span className="ml-2 font-label text-label-sm text-secondary wrap-anywhere">
                      {item.code}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="m-0 text-body-sm text-on-surface-variant">
              What you can do: {action.charAt(0).toLowerCase()}
              {action.slice(1)}
            </p>
          </div>
        );
      })}
      {showExpired && (
        <div
          role="group"
          aria-label={EXPIRED_GROUP.heading}
          data-class="expired"
          className={groupClass}
        >
          <h4 className="m-0 font-label text-label-md font-bold text-primary">
            {EXPIRED_GROUP.heading}
          </h4>
          <p className="m-0 text-body-sm">{EXPIRED_GROUP.text}</p>
          {onRefresh && (
            <button
              type="button"
              onClick={() => void onRefresh()}
              className="self-start cursor-pointer rounded-lg border border-outline-variant bg-surface-pure px-space-md py-2 font-label text-label-md text-primary hover:bg-surface-container-high"
            >
              {EXPIRED_GROUP.action}
            </button>
          )}
        </div>
      )}
      {p.request.budget_gross != null && (
        <p className="m-0">
          Mission budget: {currency(String(p.request.budget_gross))}
        </p>
      )}
      <p
        data-testid="card-approval"
        className="m-0 text-body-sm text-secondary"
      >
        Approval: {title(p.approval_status).toLowerCase()}
      </p>
      {status === "superseded" && (
        <p className="m-0 text-body-sm">
          These terms were superseded.{" "}
          <Link to={`/purchases/${p.proposal_id}`}>
            View current revision {p.current_revision}
          </Link>
          {p.committed_revision != null &&
            ` (revision ${p.committed_revision} was accepted).`}
        </p>
      )}
    </section>
  );
}
