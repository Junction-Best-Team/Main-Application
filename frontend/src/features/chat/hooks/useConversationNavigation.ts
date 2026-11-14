import { useCallback, useEffect, useState } from "react";
import type { ConversationList } from "../../../shared/api/types";
import { ApiError } from "../../../shared/api/client";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import { listConversations } from "../api/chatApi";

export function useConversationNavigation(pathname: string) {
  const { setSession } = useAuth();
  const [data, setData] = useState<ConversationList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    },
    [setSession],
  );
  const load = useCallback(async () => {
    try {
      const page = await listConversations();
      setData((current) =>
        current && current.items.length > page.items.length
          ? {
              ...current,
              items: [
                ...page.items,
                ...current.items.filter(
                  (item) =>
                    !page.items.some((newItem) => newItem.id === item.id),
                ),
              ],
            }
          : page,
      );
      setError("");
    } catch (e) {
      fail(e);
    }
  }, [fail]);
  useEffect(() => {
    void load();
  }, [load, pathname]);
  useRefresh(load);
  async function loadMore() {
    if (data?.next_offset == null || loading) return;
    setLoading(true);
    try {
      const page = await listConversations(data.next_offset);
      setData((current) => ({
        ...page,
        items: [
          ...(current?.items ?? []),
          ...page.items.filter(
            (item) =>
              !current?.items.some((existing) => existing.id === item.id),
          ),
        ],
      }));
      setError("");
    } catch (e) {
      fail(e);
    } finally {
      setLoading(false);
    }
  }
  return { data, loading, error, loadMore };
}
