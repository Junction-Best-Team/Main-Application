import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { Schedule } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { listSchedules } from "../api/schedulesApi";

// The standing orders list: first page on load, "Show more" appends the next page by offset.
export function useSchedules() {
  const { setSession } = useAuth();
  const [items, setItems] = useState<Schedule[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const active = useRef(0);
  const loaded = useRef(false);

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else
        setError(
          e instanceof Error ? e.message : "Could not load standing orders.",
        );
    },
    [setSession],
  );

  // Loads the first page. A silent reload (the periodic refresh) keeps what was paged in.
  const refresh = useCallback(
    async (silent = false) => {
      const request = ++active.current;
      if (!silent) setLoading(true);
      try {
        const page = await listSchedules(0);
        if (request !== active.current) return;
        setItems((prev) =>
          silent
            ? [
                ...page.items,
                ...prev.filter((p) => !page.items.some((i) => i.id === p.id)),
              ]
            : page.items,
        );
        if (!silent || !loaded.current) setNextOffset(page.next_offset ?? null);
        loaded.current = true;
        setError("");
      } catch (e) {
        if (request === active.current) fail(e);
      } finally {
        if (request === active.current) setLoading(false);
      }
    },
    [fail],
  );

  const showMore = useCallback(async () => {
    if (nextOffset === null) return;
    const request = ++active.current;
    setLoading(true);
    try {
      const page = await listSchedules(nextOffset);
      if (request !== active.current) return;
      setItems((prev) => [
        ...prev,
        ...page.items.filter((i) => !prev.some((p) => p.id === i.id)),
      ]);
      setNextOffset(page.next_offset ?? null);
      setError("");
    } catch (e) {
      if (request === active.current) fail(e);
    } finally {
      if (request === active.current) setLoading(false);
    }
  }, [nextOffset, fail]);

  // Swap in a schedule returned by pause/resume so the card updates without a reload.
  const replace = useCallback(
    (next: Schedule) =>
      setItems((prev) => prev.map((s) => (s.id === next.id ? next : s))),
    [],
  );

  const invalidate = useCallback(() => {
    active.current++;
  }, []);
  useEffect(() => {
    void refresh();
    return invalidate;
  }, [refresh, invalidate]);
  const silentRefresh = useCallback(() => refresh(true), [refresh]);
  useRefresh(silentRefresh);

  return { items, nextOffset, loading, error, refresh, showMore, replace };
}
