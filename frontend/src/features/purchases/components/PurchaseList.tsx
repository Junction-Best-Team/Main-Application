import { Link } from "react-router-dom";
import type { Inbox } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge";
import { currency, dateTime } from "../../../shared/lib/format";
import { getPurchaseStatus } from "../model/purchaseStatus";
export function PurchaseList({ items }: { items: Inbox["items"] }) {
  return (
    <div className="purchase-list flex flex-col gap-4">
      {items.map((p) => (
        <Link
          className="purchase-row flex min-w-0 flex-col justify-between gap-5 rounded-xl border border-border-subtle bg-surface-pure p-5 text-on-surface hover:border-wholesale-teal hover:shadow-level-2 hover:no-underline md:flex-row md:p-6"
          key={p.proposal_id}
          to={`/purchases/${p.proposal_id}`}
        >
          <div className="min-w-0 [&_h2]:mt-3 [&_h2]:mb-2 [&_h2]:wrap-anywhere [&_h2]:text-headline-sm [&_p]:mb-2 [&_p]:wrap-anywhere [&_p]:text-body-sm">
            <Badge value={getPurchaseStatus(p)} />
            <h2>{p.request.request_id}</h2>
            <p>{p.snapshot.lines.map((l) => l.name).join(", ")}</p>
            <span className="text-secondary">
              {p.agent_id} • {p.request.destination}
            </span>
          </div>
          <div className="flex shrink-0 flex-col gap-1 font-label text-label-sm text-secondary md:text-right [&_strong]:text-headline-md [&_strong]:font-bold [&_strong]:text-primary">
            <strong>{currency(p.snapshot.gross_total)}</strong>
            <span>Including tax & deposits</span>
            <span className="mt-2 text-label-sm">
              Expires {dateTime(p.expires_at)}
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}
