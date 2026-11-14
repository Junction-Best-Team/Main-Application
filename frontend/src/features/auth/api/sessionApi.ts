import { api } from "../../../shared/api/client";
import type { Session } from "../../../shared/api/types";
import type { components } from "../../../shared/api/schema";

export const getSession = () => api<Session>("/api/session");
export const signIn = (credentials: components["schemas"]["LoginRequest"]) =>
  api<Session>("/api/login", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
export const signOut = (csrfToken: string) =>
  api<void>("/api/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
