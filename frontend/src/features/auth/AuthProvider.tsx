import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../../shared/api/client";
import type { Session } from "../../shared/api/types";
import { AuthContext } from "./AuthContext";
import { getSession, signOut } from "./api/sessionApi";
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    getSession()
      .then(setSession)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401))
          setError((e as Error).message);
      })
      .finally(() => setLoading(false));
  }, []);
  async function logout() {
    try {
      await signOut(session?.csrf_token ?? "");
      setSession(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <AuthContext.Provider
      value={{ session, setSession, loading, error, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}
