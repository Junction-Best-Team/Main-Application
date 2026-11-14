import { useCallback, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { MemoryItem } from "../../../shared/api/types";
import { useAuth } from "../../auth/useAuth";
import { listMemories, type RequestScope } from "../api/memoryApi";

export type ScopeState = {
  items: MemoryItem[] | null;
  loading: boolean;
  error: string;
};
const initial: ScopeState = { items: null, loading: false, error: "" };

/** Readable messages for the memory API's stable error codes. */
const MESSAGES: Record<string, string> = {
  MEMORY_REVISION_CONFLICT:
    "This memory changed elsewhere since you opened it. Load the latest version before saving.",
  MEMORY_NOT_FOUND:
    "This memory no longer exists. It may have been removed elsewhere.",
  MEMORY_EXISTS:
    "A memory for this is already saved here. Edit the existing one instead.",
  MEMORY_LIMIT:
    "This list already holds the maximum of 50 memories. Remove one first.",
  MEMORY_SENSITIVE_DATA:
    "Memories can't store passwords, keys, tokens, account or payment details.",
  IDEMPOTENCY_CONFLICT:
    "This change clashed with an earlier attempt. Reload the page and try again.",
  ORIGIN_REJECTED:
    "Your browser session couldn't be verified. Reload the page.",
  CSRF_REJECTED: "Your browser session couldn't be verified. Reload the page.",
  AUTHORITY_REVOKED: "Your account can no longer manage memories.",
};

export function memoryErrorMessage(e: unknown): string {
  if (e instanceof ApiError && e.code && MESSAGES[e.code])
    return MESSAGES[e.code];
  if (e instanceof ApiError) return e.message;
  return "The memory service couldn't be reached. Check your connection and try again.";
}

/**
 * Server-backed lists for the two scopes, kept apart so personal and shared
 * items never mix. State lives only in memory for the mounted page; the page
 * is keyed by the signed-in identity, so a different account starts empty.
 */
export function useMemories() {
  const { setSession } = useAuth();
  const [state, setState] = useState<Record<RequestScope, ScopeState>>({
    self: initial,
    buyer: initial,
  });
  const requests = useRef<Record<RequestScope, number>>({ self: 0, buyer: 0 });

  const onError = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) {
        setSession(null);
        return true;
      }
      return false;
    },
    [setSession],
  );

  const load = useCallback(
    async (scope: RequestScope): Promise<MemoryItem[] | null> => {
      const request = ++requests.current[scope];
      setState((s) => ({
        ...s,
        [scope]: { ...s[scope], loading: true, error: "" },
      }));
      try {
        const items = await listMemories(scope);
        if (request !== requests.current[scope]) return null;
        setState((s) => ({
          ...s,
          [scope]: { items, loading: false, error: "" },
        }));
        return items;
      } catch (e) {
        if (request !== requests.current[scope] || onError(e)) return null;
        setState((s) => ({
          ...s,
          [scope]: {
            ...s[scope],
            loading: false,
            error: `Memories couldn't be loaded. ${memoryErrorMessage(e)}`,
          },
        }));
        return null;
      }
    },
    [onError],
  );

  /** Applies a server-confirmed write to the displayed list. */
  const applySaved = useCallback((scope: RequestScope, item: MemoryItem) => {
    setState((s) => {
      const items = s[scope].items;
      if (!items) return s;
      const next = items.some((i) => i.id === item.id)
        ? items.map((i) => (i.id === item.id ? item : i))
        : [item, ...items];
      return { ...s, [scope]: { ...s[scope], items: next } };
    });
  }, []);

  const applyDeleted = useCallback((scope: RequestScope, id: string) => {
    setState((s) => {
      const items = s[scope].items;
      if (!items) return s;
      return {
        ...s,
        [scope]: { ...s[scope], items: items.filter((i) => i.id !== id) },
      };
    });
  }, []);

  return { state, load, applySaved, applyDeleted, onError };
}

/**
 * One idempotency key per distinct submission: retrying the same content
 * reuses the key (so a lost response replays instead of duplicating), and
 * changed content gets a fresh key (reusing one would be rejected).
 */
export function useRetryKey(action: string) {
  const last = useRef<{ payload: string; key: string } | null>(null);
  const keyFor = useCallback(
    (payload: unknown) => {
      const serialized = JSON.stringify(payload);
      if (last.current?.payload !== serialized)
        last.current = {
          payload: serialized,
          key: `memory-${action}-${crypto.randomUUID()}`,
        };
      return last.current.key;
    },
    [action],
  );
  const reset = useCallback(() => {
    last.current = null;
  }, []);
  return { keyFor, reset };
}
