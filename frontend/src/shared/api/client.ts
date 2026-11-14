import type { components } from "./schema";

// Every error response is {"error": {"code", "message", "details"?}} (TCT-008).
type ErrorBody = components["schemas"]["ErrorBody"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public details?: ErrorBody["details"],
  ) {
    super(message);
  }
}

const FALLBACK = "The service could not complete this request. Try again.";

function errorMessage(status: number, error?: Partial<ErrorBody>): string {
  // The validation summary names raw field names; the form gets plain text, `details` has the rest.
  if (error?.code === "VALIDATION_ERROR" || (!error?.message && status === 422))
    return "Check the submitted values.";
  return error?.message || FALLBACK;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const error: Partial<ErrorBody> | undefined =
      body && typeof body === "object" ? body.error : undefined;
    throw new ApiError(
      r.status,
      errorMessage(r.status, error),
      error?.code,
      error?.details,
    );
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
