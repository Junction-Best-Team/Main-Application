import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { Inbox } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { listPurchases } from "../api/purchasesApi";
export function usePurchases() {
  const { setSession } = useAuth();
  const [data, setData] = useState<Inbox | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await listPurchases(offset));
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [offset, setSession]);
  useEffect(() => {
    void load();
  }, [load]);
  useRefresh(load);
  return { data, offset, setOffset, error, busy, load };
}
