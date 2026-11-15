import type { components } from "./schema";

// Every error response is {"error": {"code", "message", "details"?}} (TCT-008).
type ErrorBody = components["schemas"]["ErrorBody"];

// Support context kept on every failed call; only used by the debug-mode Copy link.
export type ErrorDebug = {
  method?: string;
  path?: string;
  status?: number;
  code?: string;
  requestId?: string;
  statusText?: string;
  contentType?: string;
  // Only the kind of body, never its text.
  body?: "JSON envelope" | "JSON, no error envelope" | "not JSON";
  elapsedMs?: number;
  // True when fetch itself failed, so no response exists.
  noResponse?: boolean;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public details?: ErrorBody["details"],
    public debug?: ErrorDebug,
  ) {
    super(message);
  }
}

// What a screen keeps for a shown error: the visible text plus the optional debug context.
export type ErrorInfo = { message: string; debug?: ErrorDebug };
export const noError: ErrorInfo = { message: "" };
export function toErrorInfo(e: unknown): ErrorInfo {
  return {
    message: (e as Error).message,
    debug: e instanceof ApiError ? e.debug : undefined,
  };
}

function apiPath(path: string): string {
  return path.split(/[?#]/)[0];
}

const FALLBACK = "The service could not complete this request. Try again.";

function errorMessage(status: number, error?: Partial<ErrorBody>): string {
  // The validation summary names raw field names; the form gets plain text, `details` has the rest.
  if (error?.code === "VALIDATION_ERROR" || (!error?.message && status === 422))
    return "Check the submitted values.";
  return error?.message || FALLBACK;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let r: Response;
  const started = performance.now();
  const elapsed = () => Math.round(performance.now() - started);
  try {
    r = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    // fetch rejects with the browser's own text ("Failed to fetch"); show a plain sentence.
    throw new ApiError(
      0,
      "Could not reach the service. Check your connection and try again.",
      "NETWORK_ERROR",
      undefined,
      {
        method: (options?.method ?? "GET").toUpperCase(),
        path: apiPath(path),
        status: 0,
        code: "NETWORK_ERROR",
        elapsedMs: elapsed(),
        noResponse: true,
      },
    );
  }
  if (!r.ok) {
    let parsed = true;
    const body = await r.json().catch(() => {
      parsed = false;
      return {};
    });
    const error: Partial<ErrorBody> | undefined =
      body && typeof body === "object" ? body.error : undefined;
    throw new ApiError(
      r.status,
      errorMessage(r.status, error),
      error?.code,
      error?.details,
      {
        method: (options?.method ?? "GET").toUpperCase(),
        path: apiPath(path),
        status: r.status,
        code: error?.code,
        requestId: r.headers.get("x-request-id") ?? undefined,
        statusText: r.statusText || undefined,
        contentType: r.headers.get("content-type") ?? undefined,
        body: !parsed
          ? "not JSON"
          : error && typeof error === "object"
            ? "JSON envelope"
            : "JSON, no error envelope",
        elapsedMs: elapsed(),
      },
    );
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
