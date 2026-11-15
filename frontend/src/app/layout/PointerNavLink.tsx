import type { MouseEvent, ReactNode } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { SNAPPY_SPRING } from "../../shared/lib/springs";

// iPadOS-style pointer for the sidebar nav (our take on Motion+'s "iOS pointer", which is
// paid): a hover highlight glides between items on a spring; the items stay still. The
// current page has its own highlight, so over it the hover highlight is invisible. Mouse only.
export function PointerNavLink({
  to,
  highlighted,
  dimmed = false,
  onHover,
  onClick,
  ariaCurrent,
  className,
  children,
}: {
  to: string;
  /** The mouse is over this item: it holds the gliding hover highlight. */
  highlighted: boolean;
  /** Hide the hover highlight here (the item is already highlighted). */
  dimmed?: boolean;
  onHover: () => void;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
  ariaCurrent?: "page" | "true";
  className: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <Link
      to={to}
      onClick={onClick}
      aria-current={ariaCurrent}
      className={`relative isolate ${className}`}
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") onHover();
      }}
    >
      <AnimatePresence>
        {highlighted && (
          <motion.span
            layoutId="nav-pointer"
            aria-hidden="true"
            className="absolute inset-0 -z-10 rounded-lg bg-workspace-active/70"
            initial={{ opacity: 0 }}
            animate={{ opacity: dimmed ? 0 : 1 }}
            exit={{ opacity: 0 }}
            transition={reduced ? { duration: 0 } : SNAPPY_SPRING}
          />
        )}
      </AnimatePresence>
      {children}
    </Link>
  );
}
