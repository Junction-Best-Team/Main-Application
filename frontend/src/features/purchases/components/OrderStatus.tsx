import { motion, useReducedMotion } from "motion/react";
import type { OrderListItem } from "../../../shared/api/types";
import { stageOf, type Tone } from "../model/orderStage";

// An order's status: the status word on the left (the only text), then its journey as four
// stops (Placed or Scheduled, Paid, Delivered, Confirmed) joined by a bar that fills up to the
// current stage. Each state has its own look so it reads at a glance:
//   Pending           amber, first stop a breathing ring (waiting for the customer)
//   Scheduled         grey-blue, first stop a hollow ring (not placed yet)
//   Scheduled+paused  greyed, dashed bars (on hold; the row also shows a Paused badge)
//   Placed            teal, first stop filled
//   Paid              teal, filled to the second stop (fulfilment "preparing")
//   Out for delivery  lime, bar half way to Delivered with a moving glint
//   Delivered         green, filled to the third stop
//   Confirmed         green, all stops filled
//   Cancelled         red stop where it ended, the rest of the way dashed
// The word carries the `badge <status>` classes and plain status word that tests and screen
// readers rely on; stop names are in each dot's tooltip.

const TONE: Record<Tone, { text: string; solid: string; border: string }> = {
  neutral: {
    text: "text-secondary",
    solid: "bg-secondary",
    border: "border-secondary",
  },
  muted: {
    text: "text-outline",
    solid: "bg-outline",
    border: "border-outline",
  },
  teal: {
    text: "text-wholesale-teal",
    solid: "bg-wholesale-teal",
    border: "border-wholesale-teal",
  },
  amber: {
    text: "text-amber-700 dark:text-amber-300",
    solid: "bg-amber-500",
    border: "border-amber-500",
  },
  lime: {
    text: "text-tertiary-container dark:text-tertiary",
    solid: "bg-status-fresh-green",
    border: "border-status-fresh-green",
  },
  green: {
    text: "text-green-700 dark:text-green-300",
    solid: "bg-green-600",
    border: "border-green-600",
  },
  error: { text: "text-error", solid: "bg-error", border: "border-error" },
};

const STOPS = ["Placed", "Paid", "Delivered", "Confirmed"];
const DASHED =
  "bg-[repeating-linear-gradient(90deg,var(--color-outline-variant)_0_4px,transparent_4px_8px)]";

export function OrderStatus({ item }: { item: OrderListItem }) {
  const reduced = useReducedMotion();
  const stage = stageOf(item);
  const tone = TONE[stage.tone];
  const current = Math.floor(stage.progress);
  return (
    <span className="inline-flex h-[26px] shrink-0 items-center gap-space-sm">
      <span
        className={`badge ${stage.key} shrink-0 whitespace-nowrap font-label text-label-sm font-bold ${tone.text}`}
      >
        {stage.label}
      </span>
      <span aria-hidden="true" className="flex items-center">
        {STOPS.map((stop, i) => {
          const n = i + 1;
          const name =
            n === 1 && item.status === "scheduled" ? "Scheduled" : stop;
          const isCurrent = current === n;
          const reached = stage.progress >= n && !(isCurrent && stage.hollow);
          // How much of the bar leading into this stop is filled (0..1).
          const fill = stage.cancelled
            ? 0
            : Math.min(1, Math.max(0, stage.progress - (n - 1)));
          const glint = stage.live && !stage.hollow && fill > 0 && fill < 1;
          return (
            <span key={stop} className="flex items-center">
              {i > 0 && (
                <span
                  className={`relative mx-1 h-1 w-12 overflow-hidden rounded-full sm:w-16 ${stage.dashed && !reached ? DASHED : "bg-outline-variant/50"}`}
                >
                  <motion.span
                    className={`absolute inset-y-0 left-0 overflow-hidden rounded-full ${tone.solid}`}
                    initial={{ width: "0%" }}
                    animate={{ width: `${fill * 100}%` }}
                    transition={
                      reduced
                        ? { duration: 0 }
                        : {
                            duration: 0.6,
                            delay: 0.15 * i,
                            ease: [0.2, 0.8, 0.2, 1],
                          }
                    }
                  >
                    {glint && !reduced && (
                      <motion.span
                        className="absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-white/80 to-transparent"
                        initial={{ x: "-100%" }}
                        animate={{ x: "250%" }}
                        transition={{
                          duration: 1.4,
                          repeat: Infinity,
                          ease: "easeInOut",
                        }}
                      />
                    )}
                  </motion.span>
                </span>
              )}
              <span title={name} className="relative flex h-2.5 w-2.5">
                {isCurrent && stage.live && stage.hollow && !reduced && (
                  <motion.span
                    className={`absolute inset-0 rounded-full ${tone.solid}`}
                    animate={{ scale: [1, 2.2], opacity: [0.5, 0] }}
                    transition={{
                      duration: 1.6,
                      repeat: Infinity,
                      ease: "easeOut",
                    }}
                  />
                )}
                <span
                  className={`relative h-2.5 w-2.5 rounded-full ${
                    isCurrent && stage.hollow
                      ? `border-2 bg-surface-pure ${tone.border}`
                      : reached
                        ? tone.solid
                        : "bg-outline-variant"
                  }`}
                />
              </span>
            </span>
          );
        })}
      </span>
    </span>
  );
}
