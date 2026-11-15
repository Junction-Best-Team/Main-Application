import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { Schedule } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { isSuperseded } from "../../schedules/model/scheduleStatus";
import { listRecentSchedules } from "../api/homeApi";

// The last list is kept for the page load, so Home shows the card at once when the buyer
// comes back (and can slide it in already filled); it is still refreshed on every visit.
let cached: Schedule[] | null = null;
let inflight: Promise<Schedule[]> | null = null;

function fetchStandingOrders(limit: number): Promise<Schedule[]> {
  inflight ??= listRecentSchedules(limit)
    // A restarted schedule is shown through its successor.
    .then((page) => (cached = page.items.filter((s) => !isSuperseded(s))))
    .finally(() => (inflight = null));
  return inflight;
}

/** Warms the cache before Home mounts (e.g. on "New request" from a chat). */
export function prefetchStandingOrders(limit = 3) {
  void fetchStandingOrders(limit).catch(() => undefined);
}

export function useStandingOrders(limit = 3) {
  const { setSession } = useAuth();
  const [schedules, setSchedules] = useState<Schedule[]>(cached ?? []);
  const [loading, setLoading] = useState(cached === null);
  const [error, setError] = useState("");
  const active = useRef(0);
  const invalidate = useCallback(() => {
    active.current++;
  }, []);
  const refresh = useCallback(async () => {
    const request = ++active.current;
    try {
      const items = await fetchStandingOrders(limit);
      if (request !== active.current) return;
      setSchedules(items);
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
