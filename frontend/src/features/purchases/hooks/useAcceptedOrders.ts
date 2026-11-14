import { useCallback, useEffect, useRef, useState } from "react";
import type { Proposal } from "../../../shared/api/types";
import { ApiError } from "../../../shared/api/client";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { listPurchases } from "../api/purchasesApi";
import { isAccepted } from "../model/acceptedOrders";

// Read every proposal page needed to fill the accepted-order list; pending
// purchases are still accessible from their conversations and historical links.
export function useAcceptedOrders(pageSize = 5) {
  const { setSession } = useAuth();
  const [orders, setOrders] = useState<Proposal[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const active = useRef(0);
  const held = useRef(orders);
  held.current = orders;
  const fetchPage = useCallback(
    async (from: number, existing: Proposal[], want: number) => {
      const request = ++active.current;
      setLoading(true);
      try {
        let offset: number | null = from;
        let all = existing;
        const visited = new Set<number>();
        while (offset !== null && !visited.has(offset)) {
          visited.add(offset);
          const page = await listPurchases(offset);
          all = [
            ...all,
            ...page.items.filter(
              (p) =>
                isAccepted(p) &&
                !all.some((item) => item.proposal_id === p.proposal_id),
            ),
          ];
          offset = page.next_offset ?? null;
          if (all.length >= want) break;
        }
        if (request === active.current) {
          setOrders(all);
          setNextOffset(offset);
          setError("");
        }
      } catch (e) {
        if (request !== active.current) return;
        if (e instanceof ApiError && e.status === 401) setSession(null);
        else setError((e as Error).message);
      } finally {
        if (request === active.current) setLoading(false);
      }
    },
    [setSession],
  );
  const refresh = useCallback(
    () => fetchPage(0, [], Math.max(pageSize, held.current.length)),
    [fetchPage, pageSize],
  );
  const invalidate = useCallback(() => {
    active.current++;
  }, []);
  useEffect(() => {
    void refresh();
    return invalidate;
  }, [refresh, invalidate]);
  useRefresh(refresh);
  const showMore = () =>
    nextOffset === null || loading
      ? Promise.resolve()
      : fetchPage(nextOffset, orders, orders.length + pageSize);
  return { orders, nextOffset, loading, error, refresh, showMore };
}
