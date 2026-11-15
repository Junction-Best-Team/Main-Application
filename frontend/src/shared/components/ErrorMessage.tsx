import { useEffect, useRef, useState } from "react";
import type { ErrorDebug } from "../api/client";
import { copyText } from "../lib/copyText";
import { isDebugMode } from "../lib/debug";
import { buildDebugMessage } from "../lib/debugMessage";

// Debug mode only: a text link that copies a support message (see debugMessage.ts).
function CopyDebugLink({
  message,
  debug,
}: {
  message: string;
  debug?: ErrorDebug;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <button
      type="button"
      className="ml-2 cursor-pointer border-0 bg-transparent p-0 font-label text-label-sm text-on-error-container underline"
      onClick={() => {
        void copyText(buildDebugMessage(message, debug)).then((ok) => {
          if (!ok) return;
          setCopied(true);
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setCopied(false), 2000);
        });
      }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function ErrorMessage({
  message,
  debug,
}: {
  message: string;
  debug?: ErrorDebug;
}) {
  return message ? (
    <div
      className="error my-4 rounded-lg border border-error/20 bg-error-container px-4 py-3 text-body-sm text-on-error-container"
      role="alert"
    >
      {message}
      {isDebugMode() && <CopyDebugLink message={message} debug={debug} />}
    </div>
  ) : null;
}
