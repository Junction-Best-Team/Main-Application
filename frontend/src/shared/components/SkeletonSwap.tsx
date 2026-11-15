import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { SNAPPY_SPRING } from "../lib/springs";

// Skeleton -> content, item by item. Each slot holds skeleton i until the data arrives, then
// crossfades it into item i in place; the slot's height glides to the item's real height.
// Skeletons beyond the number of loaded items fade out. Skeletons mirror their item's
// layout, so the heights normally already match.
export function SkeletonList<T>({
  loading,
  items,
  count,
  itemKey,
  renderItem,
  renderSkeleton,
  className = "",
  label,
}: {
  /** First load only; later pages keep the loaded items on screen. */
  loading: boolean;
  items: T[];
  /** How many skeletons to show while loading. */
  count: number;
  itemKey: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => ReactNode;
  renderSkeleton: (index: number) => ReactNode;
  className?: string;
  /** Announced while loading, e.g. "Loading orders…". */
  label: string;
}) {
  const slots = loading ? count : items.length;
  return (
    <div className="relative">
      {loading && (
        <p role="status" className="sr-only">
          {label}
        </p>
      )}
      <div className={className}>
        <AnimatePresence mode="popLayout" initial={false}>
          {Array.from({ length: slots }, (_, index) => (
            <motion.div
              key={`slot-${index}`}
              className="min-w-0"
              // Extra skeletons just fade away.
              exit={{ opacity: 0, transition: { duration: 0.25 } }}
            >
              <Slot>
                <AnimatePresence mode="popLayout" initial={false}>
                  {loading ? (
                    <motion.div
                      key="skeleton"
                      aria-hidden="true"
                      exit={{ opacity: 0, transition: { duration: 0.3 } }}
                    >
                      {renderSkeleton(index)}
                    </motion.div>
                  ) : (
                    <motion.div
                      key={itemKey(items[index], index)}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1, transition: { duration: 0.3 } }}
                    >
                      {renderItem(items[index], index)}
                    </motion.div>
                  )}
                </AnimatePresence>
              </Slot>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

/** Animates its own height to whatever its content measures. */
function Slot({ children }: { children: ReactNode }) {
  const inner = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | "auto">("auto");
  const reduced = useReducedMotion();
  useLayoutEffect(() => {
    const el = inner.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setHeight(el.offsetHeight));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <motion.div
      // Clip only the moving edge; card shadows may still spill out.
      className="relative [overflow:clip] [overflow-clip-margin:1rem]"
      initial={false}
      animate={{ height }}
      transition={reduced ? { duration: 0 } : SNAPPY_SPRING}
    >
      <div ref={inner}>{children}</div>
    </motion.div>
  );
}

/** A placeholder line: a box of the real line's height with a rounded bar inside, so a
 *  skeleton built from these has the same height as the text it stands for. */
export function SkeletonLine({
  height,
  bar = "h-3.5",
  width = "w-full",
  className = "",
}: {
  /** The real line's height class, e.g. "h-7" for headline-sm. */
  height: string;
  bar?: string;
  width?: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`flex items-center ${height} ${className}`}
    >
      <SkeletonBar className={`${bar} ${width}`} />
    </span>
  );
}

/** A grey placeholder bar; pulses unless the user prefers reduced motion. */
export function SkeletonBar({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`block rounded-md bg-surface-container-high motion-safe:animate-pulse ${className}`}
    />
  );
}
