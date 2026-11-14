import { api } from "../../../shared/api/client";
import type {
  MemoryCreate,
  MemoryDelete,
  MemoryItem,
  MemoryList,
  MemoryMutation,
  MemoryUpdate,
} from "../../../shared/api/types";

/** The browser names its own scope; the server resolves the actual owner. */
export type RequestScope = MemoryCreate["scope"];

const PAGE_SIZE = 50;
const MAX_OFFSET = 100; // GET /api/memories rejects a larger offset.

/** Every saved item of one scope. Owners hold at most 50 items, so this stays bounded. */
export async function listMemories(scope: RequestScope): Promise<MemoryItem[]> {
  const items: MemoryItem[] = [];
  let offset: number | null | undefined = 0;
  while (offset != null && offset <= MAX_OFFSET) {
    const page: MemoryList = await api<MemoryList>(
      `/api/memories?scope=${scope}&offset=${offset}&limit=${PAGE_SIZE}`,
    );
    items.push(...page.items.filter((i) => !items.some((x) => x.id === i.id)));
    offset = page.next_offset;
  }
  return items;
}

export const createMemory = (body: MemoryCreate, csrfToken: string) =>
  api<MemoryMutation>("/api/memories", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });

export const updateMemory = (
  id: string,
  body: MemoryUpdate,
  csrfToken: string,
) =>
  api<MemoryMutation>(`/api/memories/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });

export const deleteMemory = (
  id: string,
  body: MemoryDelete,
  csrfToken: string,
) =>
  api<MemoryMutation>(`/api/memories/${encodeURIComponent(id)}/delete`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });
