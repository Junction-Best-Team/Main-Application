import { useCallback, useEffect, useRef, useState } from "react";
import { cardLog } from "../model/cardLog";

const KEY = "aimo.cart.open";

// The cart card is open by default; the customer's choice is kept in this browser only. Storage can
// throw (private window, blocked site data), so every access is guarded and the card then stays open.
function stored(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}
const read = () => stored() !== "0";
const mounts: Record<string, number> = {};

/**
 * Open or collapsed: set only by the customer's click, never by an update to the cart.
 * In debug mode every appearance and every click is logged with the reason (default, stored
 * preference, remount, user toggle) so a card that is closed unexpectedly can be diagnosed.
 */
export function useCartOpen(component = "card"): [boolean, () => void] {
  const [open, setOpen] = useState(read);
  const clicked = useRef(false);
  useEffect(() => {
    mounts[component] = (mounts[component] ?? 0) + 1;
    const why = stored() === null ? "default" : "stored preference";
    cardLog({
      kind: "open",
      component,
      open: read(),
      why: mounts[component] > 1 ? `remount: ${why}` : why,
    });
  }, [component]);
  useEffect(() => {
    if (clicked.current)
      cardLog({ kind: "open", component, open, why: "user toggle" });
  }, [open, component]);
  const toggle = useCallback(() => {
    clicked.current = true;
    setOpen((current) => {
      try {
        window.localStorage.setItem(KEY, current ? "0" : "1");
      } catch {
        /* the choice just is not remembered */
      }
      return !current;
    });
  }, []);
  return [open, toggle];
}
