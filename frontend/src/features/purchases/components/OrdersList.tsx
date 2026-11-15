import type { OrderListItem, Proposal } from "../../../shared/api/types";
import {
  SkeletonLine,
  SkeletonList,
} from "../../../shared/components/SkeletonSwap";
import { orderKey } from "../model/orders";
import { OrderRow } from "./OrderRow";

export function OrdersList({
  items,
  loading = false,
  expanded,
  toggle,
  known,
  cancelling,
  notices,
  onCancel,
}: {
  items: OrderListItem[];
  /** First load: skeleton rows that turn into the orders one by one. */
  loading?: boolean;
  expanded: Set<string>;
  toggle: (proposalId: string) => void;
  /** A proposal the page already loaded (deep link); its placed row uses it without refetching. */
  known: Proposal | null;
  cancelling: string | null;
  notices: Record<string, string>;
  onCancel: (proposalId: string) => Promise<void>;
}) {
  return (
    <SkeletonList
      loading={loading}
      items={items}
      count={5}
      label="Loading orders…"
      className="flex flex-col gap-space-md"
      itemKey={orderKey}
      renderSkeleton={() => <OrderRowSkeleton />}
      renderItem={(item, index) => (
        <OrderRow
          item={item}
          decorVariant={index}
          expanded={Boolean(item.proposal_id && expanded.has(item.proposal_id))}
          onToggle={toggle}
          known={
            known && item.proposal_id === known.proposal_id ? known : undefined
          }
          cancelling={cancelling !== null}
          notice={item.proposal_id ? notices[item.proposal_id] : undefined}
          onCancel={onCancel}
        />
      )}
    />
  );
}

/** OrderRow's layout with placeholder lines of the same heights: badge row (26px),
 *  headline-sm title (28px), body-sm line count (20px); on the right the 26px date, the 32px
 *  total and the 34px action row with its action button and the square details button. */
function OrderRowSkeleton() {
  return (
    <div className="min-w-0 rounded-xl bg-surface-pure p-space-md shadow-level-2 md:p-space-lg">
      <div className="flex flex-col justify-between gap-space-md lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
          <div className="flex items-center gap-space-sm">
            <SkeletonLine
              height="h-[26px]"
              bar="h-[26px] rounded-full"
              width="w-20"
            />
            <SkeletonLine height="h-[26px]" bar="h-3" width="w-28" />
          </div>
          <SkeletonLine height="h-7" bar="h-5" width="w-2/5" />
          <SkeletonLine height="h-5" bar="h-3" width="w-16" />
        </div>
        <div className="flex flex-col gap-space-xs lg:items-end">
          <SkeletonLine height="h-[26px]" bar="h-3" width="w-36" />
          <SkeletonLine height="h-8" bar="h-6" width="w-32" />
          <div className="flex items-center gap-space-sm">
            <SkeletonLine height="h-[34px]" bar="h-[34px]" width="w-40" />
            <SkeletonLine height="h-[34px]" bar="h-[34px]" width="w-[34px]" />
          </div>
        </div>
      </div>
    </div>
  );
}
