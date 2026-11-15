import { useRef, useState } from "react";
import { ApiError, type ErrorDebug } from "../../../shared/api/client";
import type { Proposal } from "../../../shared/api/types";
import { newIdempotencyKey } from "../../../shared/lib/idempotency";
import { useAuth } from "../../auth/useAuth";
import { prepareFromCart } from "../api/cartApi";
import { CART_COPY } from "../model/cartCopy";

/**
 * Prepares the purchase from the conversation's cart (POST prepare-from-cart). The same `signature`
 * (cart, date, destination) reuses one request id until it succeeds, so a retry of one press cannot
 * prepare two purchases; a changed signature gets a new id.
 */
export function usePrepareFromCart(
  conversationId: string | undefined,
  onPrepared?: (proposal: Proposal) => void,
) {
  const { session } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorDebug, setErrorDebug] = useState<ErrorDebug | undefined>();
  const key = useRef<{ signature: string; value: string } | null>(null);
  async function prepare(
    delivery: { date: string; destination: string },
    signature: unknown,
  ) {
    if (!session || !conversationId || busy) return;
    const sig = JSON.stringify([
      signature,
      delivery.date,
      delivery.destination,
    ]);
    if (key.current?.signature !== sig)
      key.current = { signature: sig, value: newIdempotencyKey() };
    setBusy(true);
    setError("");
    setErrorDebug(undefined);
    try {
      const result = await prepareFromCart(session.csrf_token, conversationId, {
        delivery_date: delivery.date,
        destination: delivery.destination,
        request_id: key.current.value,
      });
      key.current = null; // the next press is a new request
      onPrepared?.(result.proposal);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : CART_COPY.prepareFailed);
      setErrorDebug(e instanceof ApiError ? e.debug : undefined);
    } finally {
      setBusy(false);
    }
  }
  return { prepare, busy, error, errorDebug };
}
