import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { OrderListItem } from "../../../shared/api/types";
import { listOrders } from "../../purchases/api/ordersApi";
import { useAuth } from "../../auth/useAuth";

const PAGE = 50;

// The customer's placed orders (the choices when restarting a stopped standing order): the
// server filters with ?status=placed and `total` says whether more exist than the page shows.
export function usePlacedOrders(enabled: boolean) {
  const { setSession } = useAuth();
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");
  const [more, setMore] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = await listOrders(0, PAGE, "placed");
      setOrders(page.items.filter((o) => o.status === "placed" && o.order_id));
      setMore(page.next_offset != null || page.total > page.items.length);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [setSession]);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  return { orders, loading, error, more, retry: load };
}
