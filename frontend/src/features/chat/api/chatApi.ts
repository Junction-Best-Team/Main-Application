import { api } from "../../../shared/api/client";
import type { Conversation, ConversationList } from "../../../shared/api/types";
import type { components } from "../../../shared/api/schema";

export const listConversations = (offset = 0) =>
  api<ConversationList>(
    offset === 0
      ? "/api/conversations?limit=30"
      : `/api/conversations?limit=30&offset=${offset}`,
  );
export const getConversation = (id: string, signal?: AbortSignal) =>
  api<Conversation>(`/api/conversations/${id}`, { signal });
export const createConversation = (
  request: components["schemas"]["ConversationCreate"],
  csrfToken: string,
  signal?: AbortSignal,
) =>
  api<Conversation>("/api/conversations", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(request),
    signal,
  });
export const sendMessage = (
  id: string,
  request: components["schemas"]["MessageRequest"],
  csrfToken: string,
  signal?: AbortSignal,
) =>
  api<Conversation>(`/api/conversations/${id}/messages`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(request),
    signal,
  });
export const openConversationEvents = (id: string) =>
  new EventSource(`/api/conversations/${id}/events`);
