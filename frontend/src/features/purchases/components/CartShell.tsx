import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { appleSpring } from "../../../shared/lib/springs";

// The chat's cart card ("Your order"), shared by the draft and the prepared basket panels.
// Open (the default; the choice is remembered by useCartOpen): on desktop a floating box one
// gap away from the chat box that takes all the height available; on phones a box under the
// chat. Collapsing animates the desktop column's width (box + gap) to zero, so the chat box
// widens at exactly the rate the cart narrows, while the cart slides out to the right; then a
// cart button slides in from the right edge into the top-right corner of the screen, as if
// the cart had teleported there. That button reverses it. Collapsed, the whole card (including
// its purchase button) is behind the corner button.

const SNAP = appleSpring(0.5, 0.86);
const GAP = 24; // md:gap-space-lg, the chat page's gap between columns
const OPEN_LG = 320;
const OPEN_XL = 384;
/** Desktop corner button: 56px square, 16px from the top, so it has the same 16px above it
 *  as below it to the chat box (which starts 88px down: 24px padding, 48px assistant
 *  header, 16px gap). */
const CORNER = "right-4 top-4 h-14 w-14";

function useMedia(query: string) {
  const [matches, setMatches] = useState(
    () => window.matchMedia(query).matches,
  );
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

export function CartShell({
  id,
  label,
  title,
  open,
  onToggle,
  headerExtra,
  count,
  busy = false,
  children,
}: {
  id?: string;
  /** The landmark's accessible name ("Your order", "Overview"). */
  label: string;
  title: string;
  open: boolean;
  onToggle: () => void;
  /** Extra items in the header beside the toggle (debug copy link, item count). */
  headerExtra?: ReactNode;
  /** Shown as a badge on the collapsed button. */
  count?: number;
  /** Aimo is working on this cart: dimmed and marked busy. */
  busy?: boolean;
  children: ReactNode;
}) {
  const desktop = useMedia("(min-width: 1024px)");
  const wide = useMedia("(min-width: 1280px)");
  const reduced = useReducedMotion();
  const spring = reduced ? { duration: 0 } : SNAP;
  const toggleLabel = open ? "Collapse cart" : "Expand cart";

  const header = (
    <div className="flex items-center justify-between gap-space-sm border-b border-border-subtle pb-space-sm">
      <h2 className="m-0 flex min-w-0 items-center gap-space-sm font-headline text-headline-sm font-bold text-primary">
        <Icon name="shopping_cart" className="text-[22px]" />
        <span className="truncate">{title}</span>
      </h2>
      <span className="flex shrink-0 items-center gap-space-xs">
        {headerExtra}
        <button
          type="button"
          aria-label={toggleLabel}
          aria-expanded={open}
          onClick={onToggle}
          title="Collapse to the cart button"
          className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-secondary hover:bg-surface-container-high"
        >
          <Icon name={desktop ? "chevron_right" : "expand_more"} />
        </button>
      </span>
    </div>
  );

  // The corner button, shown once the cart has collapsed.
  const cornerButton = createPortal(
    <AnimatePresence>
      {!open && (
        <motion.aside
          key="cart-button"
          id={id}
          aria-label={label}
          className={`fixed z-40 overflow-hidden rounded-xl border border-border-subtle bg-surface-pure shadow-level-3 ${desktop ? CORNER : "right-3 top-[4.75rem] h-11 w-11"}`}
          // In from beyond the right edge once the cart has slid out; back out the same way.
          initial={{ x: 96, opacity: 0 }}
          animate={{
            x: 0,
            opacity: 1,
            transition: reduced ? { duration: 0 } : { ...SNAP, delay: 0.25 },
          }}
          exit={{
            x: 96,
            opacity: 0,
            transition: reduced
              ? { duration: 0 }
              : { duration: 0.18, ease: [0.4, 0, 1, 1] },
          }}
        >
          <button
            type="button"
            aria-label={toggleLabel}
            aria-expanded={false}
            onClick={onToggle}
            title="Show your order"
            // Light: a soft brand-teal tint with a teal icon; dark keeps the neutral highlight.
            className="relative flex h-full w-full cursor-pointer items-center justify-center border-0 bg-transparent p-0 text-primary transition-colors hover:bg-secondary-container/60 hover:text-wholesale-teal dark:hover:bg-surface-container-high dark:hover:text-primary"
          >
            <Icon
              name="shopping_cart"
              className={desktop ? "text-[26px]" : "text-[22px]"}
            />
            {count ? (
              <span className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-status-fresh-green px-1 font-label text-[10px] font-bold leading-none text-deep-ocean-navy">
                {count}
              </span>
            ) : null}
          </button>
        </motion.aside>
      )}
    </AnimatePresence>,
    document.body,
  );

  if (!desktop)
    return (
      <>
        {cornerButton}
        {open && (
          <aside
            id={id}
            aria-label={label}
            aria-busy={busy || undefined}
            className={`flex max-h-[45dvh] min-w-0 shrink-0 flex-col overflow-y-auto rounded-xl border border-border-subtle bg-surface-pure p-space-md shadow-sm ${busy ? "opacity-70" : ""}`}
          >
            {header}
            {children}
          </aside>
        )}
      </>
    );

  const openWidth = wide ? OPEN_XL : OPEN_LG;
  return (
    <>
      {cornerButton}
      {/* The column: its width (gap + box) is what the chat box gives up, so both move
          together and the gap stays the same. */}
      <motion.div
        className="cart-column relative flex shrink-0 justify-end self-stretch [overflow:clip] [overflow-clip-margin:12px]"
        initial={false}
        animate={{ width: open ? openWidth + GAP : 0 }}
        transition={spring}
      >
        {/* Named and focusable only while open; collapsed, the corner button is the cart. */}
        <motion.aside
          id={open ? id : undefined}
          aria-label={open ? label : undefined}
          aria-hidden={open ? undefined : true}
          aria-busy={(open && busy) || undefined}
          inert={!open}
          className={`flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-pure shadow-level-2 ${busy ? "opacity-70" : ""}`}
          initial={false}
          // Slides right as the column closes (and back in from the right as it opens).
          animate={{ x: open ? 0 : openWidth, opacity: open ? 1 : 0 }}
          transition={{
            x: open && !reduced ? { ...spring, delay: 0.12 } : spring,
            opacity: reduced
              ? { duration: 0 }
              : open
                ? { duration: 0.2, delay: 0.12 }
                : { duration: 0.3, delay: 0.1 },
          }}
          style={{ marginLeft: GAP }}
        >
          {/* Full width at all times and clipped, so nothing reflows while it moves. */}
          <div
            className="flex h-full min-h-0 flex-col p-space-md"
            style={{ width: openWidth }}
          >
            {header}
            <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          </div>
        </motion.aside>
      </motion.div>
    </>
  );
}
