import { useEffect, useRef, useState } from "react";
import { cardLogActive, copyCardLog } from "../model/cardLog";

/** Debug mode only: copies the card's state log (ids, counts, decisions) for a support message. */
export function CardLogCopy() {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  if (!cardLogActive()) return null;
  return (
    <button
      type="button"
      className="cursor-pointer border-0 bg-transparent p-0 font-label text-label-sm text-secondary underline"
      onClick={() => {
        void copyCardLog().then((ok) => {
          if (!ok) return;
          setCopied(true);
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => setCopied(false), 2000);
        });
      }}
    >
      {copied ? "Copied card log" : "Copy card log"}
    </button>
  );
}
