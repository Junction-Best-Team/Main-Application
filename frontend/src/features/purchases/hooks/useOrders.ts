import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { OrderListItem } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { cancelRequest, listOrders } from "../api/ordersApi";
import type { OrderStatus } from "../model/orders";

type Options = {
  pageSize?: number;
  /** Keep only rows of this status and read further pages until `want` of them are loaded. */
  status?: OrderStatus;
  want?: number;
};

const without = (record: Record<string, string>, key: string) =>
  Object.fromEntries(Object.entries(record).filter(([k]) => k !== key));

// GET /api/orders is paged by the server (next_offset). The 30 s refresh reloads as many
// pages as are already shown, so rows the customer has paged to do not disappear.
export function useOrders({
  pageSize = 20,
  status,
  want = pageSize,
}: Options = {}) {
  const { session, setSession } = useAuth();
  const [items, setItems] = useState<OrderListItem[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notices, setNotices] = useState<Record<string, string>>({});
  const [cancelling, setCancelling] = useState<string | null>(null);
  const active = useRef(0);
  const held = useRef(items);
  held.current = items;
  const pageCount = useRef(0);

  const fetchPages = useCallback(
    async (
      from: number,
      existing: OrderListItem[],
      pagesBefore: number,
      stop: (pages: number, shown: number) => boolean,
    ) => {
      const request = ++active.current;
      setLoading(true);
      try {
        let offset: number | null = from;
        let all = existing;
        let pages = pagesBefore;
        const visited = new Set<number>();
        while (offset !== null && !visited.has(offset)) {
          visited.add(offset);
          const page = await listOrders(offset, pageSize, status);
          pages += 1;
          all = [
            ...all,
            ...(status
              ? page.items.filter((item) => item.status === status)
              : page.items),
          ];
          offset = page.next_offset ?? null;
          if (stop(pages, all.length)) break;
        }
        if (request === active.current) {
          pageCount.current = pages;
          setItems(all);
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
    [pageSize, setSession, status],
  );

  const refresh = useCallback(
    () =>
      fetchPages(0, [], 0, (pages, shown) =>
        status
          ? shown >= Math.max(want, held.current.length)
          : pages >= Math.max(1, pageCount.current),
      ),
    [fetchPages, status, want],
  );
  const invalidate = useCallback(() => {
    active.current++;
  }, []);
  useEffect(() => {
    void refresh();
    return invalidate;
  }, [refresh, invalidate]);
  useRefresh(refresh);

  const showMore = () => {
    if (nextOffset === null || loading) return Promise.resolve();
    const before = held.current.length;
    const pagesBefore = pageCount.current;
    return fetchPages(nextOffset, held.current, pagesBefore, (pages, shown) =>
      status ? shown >= before + pageSize : pages > pagesBefore,
    );
  };

  // Cancels a pending request. The server answers 409 ORDER_ALREADY_PLACED once it was
  // ordered and 404 NOT_FOUND when it is gone; both mean the list is out of date.
  const cancel = async (proposalId: string) => {
    if (!session || cancelling) return;
    setCancelling(proposalId);
    setNotices((prev) => without(prev, proposalId));
    try {
      await cancelRequest(session.csrf_token, proposalId);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setSession(null);
        return;
      }
      const code = e instanceof ApiError ? e.code : undefined;
      const message =
        code === "ORDER_ALREADY_PLACED"
          ? "This order was already placed."
          : code === "NOT_FOUND"
            ? "This request no longer exists."
            : (e as Error).message;
      setNotices((prev) => ({ ...prev, [proposalId]: message }));
      if (code === "ORDER_ALREADY_PLACED" || code === "NOT_FOUND")
        await refresh();
    } finally {
      setCancelling(null);
    }
  };
  const dismissNotice = (proposalId: string) =>
    setNotices((prev) => without(prev, proposalId));

  return {
    items,
    nextOffset,
    loading,
    error,
    refresh,
    showMore,
    cancel,
    cancelling,
    notices,
    dismissNotice,
  };
}
