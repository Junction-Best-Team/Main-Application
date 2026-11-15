import { useEffect } from "react";
import { copyText } from "../../../shared/lib/copyText";
import { isDebugMode } from "../../../shared/lib/debug";

// State logging for diagnosing the cart card. ACTIVE ONLY IN DEBUG MODE (?debug=1): every decision
// about the card goes to the console and to window.__aimoCardLog (the last 200 entries). Entries
// carry ids, counts and state names only: never message text, item names, tokens or cookies.
const MAX = 200;
export type CardLogEntry = { t: string; kind: string } & Record<
  string,
  unknown
>;
declare global {
  interface Window {
    __aimoCardLog?: CardLogEntry[];
  }
}

export function cardLog(entry: { kind: string } & Record<string, unknown>) {
  if (!isDebugMode()) return;
  try {
    const full: CardLogEntry = { t: new Date().toISOString(), ...entry };
    const list = (window.__aimoCardLog ??= []);
    list.push(full);
    if (list.length > MAX) list.splice(0, list.length - MAX);
    console.info("[aimo-card]", JSON.stringify(full));
  } catch {
    /* logging must never break the card */
  }
}

/** Logs `entry` when its content changes (not on every render). */
export function useCardLog(
  entry: ({ kind: string } & Record<string, unknown>) | null,
) {
  const key = JSON.stringify(entry);
  useEffect(() => {
    const parsed = JSON.parse(key) as typeof entry;
    if (parsed) cardLog(parsed);
  }, [key]);
}

/** The log as text for a support message: one JSON entry per line. */
export const cardLogText = () =>
  (window.__aimoCardLog ?? []).map((e) => JSON.stringify(e)).join("\n");
export const copyCardLog = () => copyText(cardLogText());
export const cardLogActive = isDebugMode;
