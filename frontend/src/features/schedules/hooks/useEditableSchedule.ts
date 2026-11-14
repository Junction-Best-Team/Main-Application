import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { ScheduleDetail } from "../../../shared/api/types";
import { useAuth } from "../../auth/useAuth";
import { getSchedule } from "../api/schedulesApi";

// Loads the standing order the edit page starts from. `reload` fetches it again without going
// back to the loading screen (after SCHEDULE_NOT_ACTIVE).
export function useEditableSchedule(scheduleId: string | undefined) {
  const { setSession } = useAuth();
  const [schedule, setSchedule] = useState<ScheduleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);

  const fetchOnce = useCallback(
    async (id: string) => {
      try {
        const next = await getSchedule(id);
        setSchedule(next);
        setError("");
        setNotFound(false);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setSession(null);
        else if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError((e as Error).message);
      }
    },
    [setSession],
  );

  useEffect(() => {
    if (!scheduleId) return;
    let active = true;
    void fetchOnce(scheduleId).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [fetchOnce, scheduleId]);

  const reload = useCallback(
    () => (scheduleId ? fetchOnce(scheduleId) : Promise.resolve()),
    [fetchOnce, scheduleId],
  );
  return { schedule, loading, error, notFound, reload };
}
