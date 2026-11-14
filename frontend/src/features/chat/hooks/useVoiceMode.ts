import { useContext } from "react";
import { VoiceContext } from "../model/VoiceContext";

export function useVoiceMode() {
  const value = useContext(VoiceContext);
  if (!value) throw new Error("useVoiceMode requires VoiceModeProvider.");
  return value;
}
