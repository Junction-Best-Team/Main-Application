import { api } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type VoiceSession = components["schemas"]["VoiceSession"];

export const createVoiceSession = (
  conversationId: string,
  csrfToken: string,
  signal: AbortSignal,
) =>
  api<VoiceSession>(`/api/conversations/${conversationId}/voice-session`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    signal,
  });
