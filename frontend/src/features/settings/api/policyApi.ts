import { api } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type PolicySettings = components["schemas"]["PolicySettings"];
export type PolicyUpdate = components["schemas"]["PolicyUpdate"];

export const getPolicy = () => api<PolicySettings>("/api/settings/policy");
export const savePolicy = (body: PolicyUpdate, csrfToken: string) =>
  api<PolicySettings>("/api/settings/policy", {
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });
