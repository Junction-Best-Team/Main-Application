import { useCallback, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import type { SubstituteCandidate } from "../../../shared/api/types";
import { useAuth } from "../../auth/useAuth";
import { substituteCandidates } from "../api/schedulesApi";

export type CandidateState =
  | { status: "loading" }
  | { status: "ready"; candidates: SubstituteCandidate[] }
  | { status: "error"; message: string };

// Candidates are loaded per product the first time a line is opened, then kept for the page.
export function useSubstituteCandidates() {
  const { setSession } = useAuth();
  const [byProduct, setByProduct] = useState<Record<string, CandidateState>>(
    {},
  );
  const started = useRef(new Set<string>());
  const load = useCallback(
    async (productId: string, retry = false) => {
      if (started.current.has(productId) && !retry) return;
      started.current.add(productId);
      setByProduct((s) => ({ ...s, [productId]: { status: "loading" } }));
      try {
        const result = await substituteCandidates(productId);
        setByProduct((s) => ({
          ...s,
          [productId]: { status: "ready", candidates: result.candidates },
        }));
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setSession(null);
          return;
        }
        setByProduct((s) => ({
          ...s,
          [productId]: {
            status: "error",
            message: (e as Error).message || "Could not load substitutes.",
          },
        }));
      }
    },
    [setSession],
  );
  return { byProduct, load };
}
