import { useEffect, useState } from "react";

// Types the heading out letter by letter with a blinking cursor. Our own take on Motion's
// Typewriter (a paid Motion+ component), with no dependency: uneven key timing, short pauses
// after spaces and punctuation, and a cursor that blinks on for a moment before fading.
// Untyped letters stay in the layout (invisible), so the centred heading never shifts.
// Screen readers get the full text at once; reduced motion shows it without typing.

const BASE_MS = 55;
const VARIANCE_MS = 45;
const PAUSE_MS = 120;
const CURSOR_LINGER_MS = 1400;

const reducedMotion = () =>
  matchMedia("(prefers-reduced-motion: reduce)").matches;

export function TypewriterHeading({
  text,
  start = true,
}: {
  text: string;
  start?: boolean;
}) {
  const [count, setCount] = useState(() => (reducedMotion() ? text.length : 0));
  const [cursor, setCursor] = useState(!reducedMotion());

  useEffect(() => {
    if (!start || reducedMotion()) return;
    let timer: number;
    let typed = 0;
    const next = () => {
      typed += 1;
      setCount(typed);
      if (typed >= text.length) {
        timer = window.setTimeout(() => setCursor(false), CURSOR_LINGER_MS);
        return;
      }
      const previous = text[typed - 1];
      const pause = /[\s,.?!]/.test(previous) ? PAUSE_MS : 0;
      timer = window.setTimeout(
        next,
        BASE_MS + Math.random() * VARIANCE_MS + pause,
      );
    };
    timer = window.setTimeout(next, 250);
    return () => window.clearTimeout(timer);
  }, [start, text]);

  return (
    <h1 aria-label={text}>
      <span aria-hidden="true">
        {text.slice(0, count)}
        <span
          className={`typewriter-cursor${cursor ? "" : " is-done"}${count < text.length ? " is-typing" : ""}`}
        />
        <span className="invisible">{text.slice(count)}</span>
      </span>
    </h1>
  );
}
