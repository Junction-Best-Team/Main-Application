import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import { useAuth } from "../../auth/useAuth";
import {
  getPolicy,
  savePolicy,
  type PolicySettings,
  type PolicyUpdate,
} from "../api/policyApi";

export function usePolicySettings() {
  const { session, setSession } = useAuth();
  const [data, setData] = useState<PolicySettings | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  function failed(e: unknown) {
    if (e instanceof ApiError && e.status === 401) setSession(null);
    else setError((e as Error).message);
  }
  const load = useCallback(async () => {
    setBusy(true);
    setSaved(false);
    setData(null);
    try {
      setData(await getPolicy());
      setError("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [setSession]);
  useEffect(() => {
    void load();
  }, [load]);
  async function save(body: PolicyUpdate) {
    if (busy) return;
    setBusy(true);
    setSaved(false);
    setError("");
    try {
      setData(await savePolicy(body, session?.csrf_token ?? ""));
      setSaved(true);
    } catch (e) {
      failed(e);
    } finally {
      setBusy(false);
    }
  }
  return { data, busy, error, saved, load, save };
}
