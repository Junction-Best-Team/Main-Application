import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { Schedule, ScheduleDetail } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { getSchedule } from "../api/schedulesApi";

// One standing order with its newest runs. Older runs are fetched on request by runs_next_offset.
export function useSchedule(id: string | undefined) {
  const { setSession } = useAuth();
  const [schedule, setSchedule] = useState<ScheduleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [olderLoading, setOlderLoading] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(0);

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else
        setError(
          e instanceof Error
            ? e.message
            : "Could not load this standing order.",
        );
    },
    [setSession],
  );

  // A silent reload (periodic refresh, or after an action raced) keeps older runs already shown.
  const reload = useCallback(
    async (silent = false) => {
      if (!id) return;
      const request = ++active.current;
      if (!silent) setLoading(true);
      try {
        const fresh = await getSchedule(id, 0);
        if (request !== active.current) return;
        setSchedule((prev) => {
          if (!silent || !prev || prev.runs.length <= fresh.runs.length)
            return fresh;
          const older = prev.runs.filter(
            (r) => !fresh.runs.some((f) => f.id === r.id),
          );
          return {
            ...fresh,
            runs: [...fresh.runs, ...older],
            runs_next_offset: prev.runs_next_offset,
          };
        });
        setError("");
      } catch (e) {
        if (request === active.current) fail(e);
      } finally {
        if (request === active.current) setLoading(false);
      }
    },
    [id, fail],
  );

  const showOlderRuns = useCallback(async () => {
    const offset = schedule?.runs_next_offset;
    if (!id || offset == null) return;
    const request = ++active.current;
    setOlderLoading(true);
    try {
      const page = await getSchedule(id, offset);
      if (request !== active.current) return;
      setSchedule((prev) =>
        prev
          ? {
              ...prev,
              runs: [
                ...prev.runs,
                ...page.runs.filter(
                  (r) => !prev.runs.some((p) => p.id === r.id),
                ),
              ],
              runs_next_offset: page.runs_next_offset ?? null,
            }
          : prev,
      );
      setError("");
    } catch (e) {
      if (request === active.current) fail(e);
    } finally {
      if (request === active.current) setOlderLoading(false);
    }
  }, [id, schedule?.runs_next_offset, fail]);

  // Pause/resume/cancel answer with the plain schedule; the loaded runs stay as they are.
  const apply = useCallback(
    (next: Schedule) =>
      setSchedule((prev) => (prev ? { ...prev, ...next } : prev)),
    [],
  );

  const invalidate = useCallback(() => {
    active.current++;
  }, []);
  useEffect(() => {
    setSchedule(null);
    setError("");
    void reload();
    return invalidate;
  }, [reload, invalidate]);
  const silentReload = useCallback(() => reload(true), [reload]);
  useRefresh(silentReload);

  return {
    schedule,
    loading,
    olderLoading,
    error,
    reload: silentReload,
    showOlderRuns,
    apply,
  };
}
