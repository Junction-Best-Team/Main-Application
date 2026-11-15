import { createContext } from "react";
import type { VoiceState } from "./liveVoice";

export const VoiceContext = createContext<{
  /** Voice is connecting or live; the composer input stays locked. */
  active: boolean;
  /** Voice is live or still showing its last error. */
  state: VoiceState | null;
  start: (conversationId?: string) => void;
  stop: () => void;
  setMuted: (muted: boolean) => void;
  /** Current speech loudness, 0 to 1. */
  level: () => number;
} | null>(null);
