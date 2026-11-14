export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

type ErrorBody = {
  error?: { code?: string; message?: string; details?: unknown };
  detail?: { loc?: unknown[]; msg?: string }[] | string;
};

// The server answers every error as {error:{code,message,details?}}. Older routes may still
// return FastAPI's {detail:[{loc,msg}]} for validation errors (422); read both.
function readError(status: number, body: ErrorBody) {
  const fallback =
    status === 422
      ? "Check the submitted values."
      : "The service could not complete this request. Try again.";
  if (body.error?.message) {
    return {
      message: body.error.message,
      code: body.error.code,
      details: body.error.details,
    };
  }
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const first = body.detail[0];
    const field = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
    return {
      message: field
        ? `${field}: ${first.msg ?? fallback}`
        : (first.msg ?? fallback),
      code: "VALIDATION_ERROR",
      details: body.detail,
    };
  }
  return { message: fallback, code: body.error?.code, details: undefined };
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let r: Response;
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
    );
  }
  if (!r.ok) {
    const body: ErrorBody = await r.json().catch(() => ({}));
    const { message, code, details } = readError(r.status, body);
    throw new ApiError(r.status, message, code, details);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
