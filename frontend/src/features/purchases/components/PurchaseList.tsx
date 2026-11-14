import { Link } from "react-router-dom";
import type { Inbox } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge";
import { currency, dateTime } from "../../../shared/lib/format";
import { getPurchaseStatus } from "../model/purchaseStatus";
export function PurchaseList({ items }: { items: Inbox["items"] }) {
  return (
    <div className="purchase-list">
      {items.map((p) => (
        <Link
          className="purchase-row"
          key={p.proposal_id}
          to={`/purchases/${p.proposal_id}`}
        >
          <div className="row-main">
            <Badge value={getPurchaseStatus(p)} />
            <h2>{p.request.request_id}</h2>
            <p>{p.snapshot.lines.map((l) => l.name).join(", ")}</p>
            <span className="muted">
              {p.agent_id} • {p.request.destination}
            </span>
          </div>
          <div className="row-amount">
            <strong>{currency(p.snapshot.gross_total)}</strong>
            <span>Including tax & deposits</span>
            <span className="expiry">Expires {dateTime(p.expires_at)}</span>
          </div>
        </Link>
      ))}
    </div>
  );
}
