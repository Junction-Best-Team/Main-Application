export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The application's stable error code, when the server sends one. */
    public code?: string,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new ApiError(
      r.status,
      body.error?.message ||
        (r.status === 422
          ? "Check the submitted values."
          : "The service could not complete this request. Try again."),
      typeof body.error?.code === "string" ? body.error.code : undefined,
    );
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
