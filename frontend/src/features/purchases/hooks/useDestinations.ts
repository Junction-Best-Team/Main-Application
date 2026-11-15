import { useEffect, useState } from "react";
import { getPolicy } from "../../settings/api/policyApi";

/** The buyer's delivery destinations (policy rules). Empty when they cannot be read: the server decides. */
export function useDestinations(): string[] {
  const [destinations, setDestinations] = useState<string[]>([]);
  useEffect(() => {
    let active = true;
    getPolicy()
      .then((p) => {
        const list = p?.rules?.destinations;
        if (active && Array.isArray(list)) setDestinations(list);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  return destinations;
}
