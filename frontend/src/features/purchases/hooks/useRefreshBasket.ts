import { useRef, useState } from "react";
import { ApiError, type ErrorDebug } from "../../../shared/api/client";
import type { Proposal } from "../../../shared/api/types";
import { newIdempotencyKey } from "../../../shared/lib/idempotency";
import { useAuth } from "../../auth/useAuth";
import { refreshBasket } from "../api/cartApi";
import { CART_COPY } from "../model/cartCopy";

/**
 * The one handler behind the Refresh button of an expired basket: asks the server to prepare it again
 * (fresh price and stock, the customer's own amounts, never a confirmation). One request id per press,
 * reused on a retry of the same press. Outside a chat (no conversation) it just reloads the purchase.
 */
export function useRefreshBasket(
  conversationId: string | undefined,
  onRefreshed: ((proposal: Proposal) => void) | undefined,
  reload: () => unknown,
) {
  const { session } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorDebug, setErrorDebug] = useState<ErrorDebug | undefined>();
  const key = useRef<string | null>(null);
  async function refresh() {
    if (busy) return;
    if (!session || !conversationId) {
      await reload();
      return;
    }
    key.current ??= newIdempotencyKey();
    setBusy(true);
    setError("");
    setErrorDebug(undefined);
    try {
      const result = await refreshBasket(session.csrf_token, conversationId, {
        request_id: key.current,
      });
      key.current = null; // the next press is a new request
      onRefreshed?.(result.proposal);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : CART_COPY.prepareFailed);
      setErrorDebug(e instanceof ApiError ? e.debug : undefined);
    } finally {
      setBusy(false);
    }
  }
  return { refresh, busy, error, errorDebug };
}
