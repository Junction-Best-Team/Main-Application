import type { OrderListItem, Proposal } from "../../../shared/api/types";
import { orderKey } from "../model/orders";
import { OrderRow } from "./OrderRow";

export function OrdersList({
  items,
  expanded,
  toggle,
  known,
  cancelling,
  notices,
  onCancel,
}: {
  items: OrderListItem[];
  expanded: Set<string>;
  toggle: (proposalId: string) => void;
  /** A proposal the page already loaded (deep link); its placed row uses it without refetching. */
  known: Proposal | null;
  cancelling: string | null;
  notices: Record<string, string>;
  onCancel: (proposalId: string) => Promise<void>;
}) {
  return (
    <>
      {items.map((item, index) => (
        <OrderRow
          key={orderKey(item, index)}
          item={item}
          expanded={Boolean(item.proposal_id && expanded.has(item.proposal_id))}
          onToggle={toggle}
          known={
            known && item.proposal_id === known.proposal_id ? known : undefined
          }
          cancelling={cancelling !== null}
          notice={item.proposal_id ? notices[item.proposal_id] : undefined}
          onCancel={onCancel}
        />
      ))}
    </>
  );
}
