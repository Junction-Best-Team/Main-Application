import { useCallback, useEffect, useRef, useState } from "react";
import { useCardLog } from "../model/cardLog";

export type CardTabName = "items" | "delivery" | "checks" | "details";
export type TabWhy = "default" | "user click" | "edit" | "error" | "new basket";

/**
 * Which tab of the card is open. Items is the default. It goes back to Items on any edit, any error
 * and a NEW basket (a new proposal id); a basket that is only updated never changes it, and a click
 * of the customer is kept until one of those happens. Every decision goes to the debug card log.
 */
export function useCardTab(proposalId: string | undefined, errored: boolean) {
  const [state, setState] = useState<{ tab: CardTabName; why: TabWhy }>({
    tab: "items",
    why: "default",
  });
  const seen = useRef<string | undefined>(proposalId);
  useEffect(() => {
    if (!proposalId) return;
    if (seen.current !== undefined && seen.current !== proposalId)
      setState({ tab: "items", why: "new basket" });
    seen.current = proposalId;
  }, [proposalId]);
  const wasErrored = useRef(false);
  useEffect(() => {
    if (errored && !wasErrored.current)
      setState({ tab: "items", why: "error" });
    wasErrored.current = errored;
  }, [errored]);
  const select = useCallback(
    (tab: CardTabName, why: TabWhy) => setState({ tab, why }),
    [],
  );
  useCardLog({ kind: "tab", tab: state.tab, why: state.why });
  return { ...state, select };
}
