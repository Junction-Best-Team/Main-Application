import { createContext, type Dispatch, type SetStateAction } from "react";
import type { Session } from "../../shared/api/types";
export type AuthState = {
  session: Session | null;
  setSession: Dispatch<SetStateAction<Session | null>>;
  loading: boolean;
  error: string;
  logout: () => Promise<void>;
};
export const AuthContext = createContext<AuthState | null>(null);
