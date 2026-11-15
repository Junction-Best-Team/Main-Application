import type { ErrorDebug } from "../api/client";

// Plain-text support message for one error. Only the fields below are ever included: never
// cookies, CSRF tokens, request bodies, the customer's message or any response beyond the
// error envelope. Query strings are dropped from both the page and the API path.
export function buildDebugMessage(message: string, debug?: ErrorDebug): string {
  const conversation = window.location.pathname.match(
    /\/conversations\/([^/]+)/,
  )?.[1];
  const lines: Array<[string, string | number | undefined]> = [
    ["timestamp", new Date().toISOString()],
    ["page", window.location.pathname],
    ["method", debug?.method],
    ["api-path", debug?.path],
    ["status", debug?.status],
    ["status-text", debug?.statusText],
    ["content-type", debug?.contentType],
    ["body", debug?.body],
    ["elapsed-ms", debug?.elapsedMs],
    ["error-code", debug?.code],
    ["error-message", message],
    [
      "x-request-id",
      debug?.requestId ?? (debug && !debug.noResponse ? "none" : undefined),
    ],
    ["response", debug?.noResponse ? "none (network failure)" : undefined],
    ["conversation-id", conversation],
    ["user-agent", navigator.userAgent],
  ];
  return lines
    .filter(([, value]) => value !== undefined && value !== "")
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
}
