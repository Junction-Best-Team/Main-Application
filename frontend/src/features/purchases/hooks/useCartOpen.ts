import { useCallback, useState } from "react";

const KEY = "aimo.cart.open";

// The cart card is open by default; the customer's choice is kept in this browser only. Storage can
// throw (private window, blocked site data), so every access is guarded and the card then stays open.
function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "0";
  } catch {
    return true;
  }
}

/** Open or collapsed: set only by the customer's click, never by an update to the cart. */
export function useCartOpen(): [boolean, () => void] {
  const [open, setOpen] = useState(read);
  const toggle = useCallback(() => {
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
