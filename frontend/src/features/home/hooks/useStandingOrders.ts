import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { Schedule } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { isSuperseded } from "../../schedules/model/scheduleStatus";
import { listRecentSchedules } from "../api/homeApi";

export function useStandingOrders(limit = 3) {
  const { setSession } = useAuth();
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const active = useRef(0);
  const invalidate = useCallback(() => {
    active.current++;
  }, []);
  const refresh = useCallback(async () => {
    const request = ++active.current;
    try {
      const page = await listRecentSchedules(limit);
      if (request !== active.current) return;
      // A restarted schedule is shown through its successor.
      setSchedules(page.items.filter((s) => !isSuperseded(s)));
      setError("");
    } catch (e) {
      if (request !== active.current) return;
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    } finally {
      if (request === active.current) setLoading(false);
    }
  }, [limit, setSession]);
  useEffect(() => {
    void refresh();
    return invalidate;
  }, [refresh, invalidate]);
  useRefresh(refresh);
  return { schedules, loading, error };
}
