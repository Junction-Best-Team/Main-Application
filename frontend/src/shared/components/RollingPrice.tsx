import { motion, useReducedMotion } from "motion/react";
import { currency } from "../lib/format";
import { appleSpring } from "../lib/springs";

// A price that counts up from zero like an odometer when it appears: every digit is a
// column of 0-9 that rolls to its value, right-most digits first. Our own take on Motion's
// price switcher (AnimateNumber is a paid Motion+ component). The formatted price is in the
// DOM as text for screen readers and copy; the rolling columns are decorative.

const ROLL = appleSpring(0.9, 0.86);
const DIGITS = Array.from({ length: 10 }, (_, d) => d);

export function RollingPrice({
  value,
  currencyCode = "EUR",
}: {
  value: string | null | undefined;
  currencyCode?: string;
}) {
  const text = currency(value, currencyCode);
  const reduced = useReducedMotion();
  if (value == null || reduced) return <>{text}</>;
  const chars = Array.from(text);
  const digitCount = chars.filter((c) => /\d/.test(c)).length;
  let seen = 0;
  return (
    <span className="relative inline-flex tabular-nums">
      <span className="sr-only">{text}</span>
      <span aria-hidden="true" className="inline-flex">
        {chars.map((char, index) => {
          if (!/\d/.test(char))
            return (
              <span key={index} className="whitespace-pre">
                {char}
              </span>
            );
          // Right-most digits start first, like a counter carrying over.
          const order = digitCount - 1 - seen++;
          return (
            <span
              key={index}
              className="relative inline-block h-[1lh] overflow-hidden"
            >
              <motion.span
                className="flex flex-col"
                initial={{ y: "0%" }}
                animate={{ y: `${-Number(char) * 10}%` }}
                transition={{ ...ROLL, delay: 0.05 + order * 0.04 }}
              >
                {DIGITS.map((d) => (
                  <span key={d} className="block h-[1lh]">
                    {d}
                  </span>
                ))}
              </motion.span>
            </span>
          );
        })}
      </span>
    </span>
  );
}
