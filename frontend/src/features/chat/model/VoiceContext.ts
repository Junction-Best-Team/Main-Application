import { createContext } from "react";

export const VoiceContext = createContext<{
  active: boolean;
  start: (conversationId?: string) => void;
} | null>(null);
