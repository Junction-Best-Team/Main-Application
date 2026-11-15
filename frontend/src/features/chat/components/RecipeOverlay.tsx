import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import type { MealPlan } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Whole-viewport recipe overlay: near-fullscreen panel on scrim; ingredients + steps only. */
export function RecipeOverlay({
  plan,
  onClose,
}: {
  plan: MealPlan;
  onClose: () => void;
}) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const steps = plan.instructions ?? [];

  useEffect(() => {
    const previous = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const items = [
        ...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      ].filter((el) => !el.closest("[aria-hidden='true']"));
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKey);
    dialog.current
      ?.querySelector<HTMLElement>("button[aria-label='Close recipe']")
      ?.focus();

    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      if (previous instanceof HTMLElement) previous.focus({ preventScroll: true });
    };
  }, [onClose]);

  return createPortal(
    <div
      className="recipe-overlay-root fixed inset-0 z-[80] flex items-center justify-center p-3 sm:p-6"
      data-recipe-overlay=""
    >
      <button
        type="button"
        aria-label="Close recipe overlay"
        className="recipe-overlay-scrim absolute inset-0 cursor-pointer border-0 bg-deep-ocean-navy/55 p-0"
        onClick={onClose}
      />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="recipe-overlay-panel relative z-[1] flex h-[min(92dvh,100%)] w-full max-w-[min(1100px,100%)] flex-col overflow-hidden rounded-xl bg-surface-pure shadow-level-3"
      >
        <div className="flex shrink-0 items-start justify-between gap-space-sm border-b border-border-subtle px-space-md py-space-sm">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="font-headline text-headline-sm text-primary"
            >
              {plan.title}
            </h2>
            <p className="m-0 text-body-sm text-secondary">
              {plan.portions} portions · ingredients &amp; steps
            </p>
          </div>
          <button
            type="button"
            aria-label="Close recipe"
            onClick={onClose}
            className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-primary hover:bg-surface-container"
          >
            <Icon name="close" className="text-[24px]" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-space-md py-space-md">
          <section aria-label="Ingredients" className="mb-space-lg">
            <h3 className="m-0 mb-space-sm font-label text-label-md font-bold uppercase tracking-wider text-secondary">
              Ingredients
            </h3>
            {plan.ingredients.length === 0 ? (
              <p className="m-0 text-body-sm text-secondary">
                No ingredients in this plan yet.
              </p>
            ) : (
              <ul className="m-0 list-none p-0">
                {plan.ingredients.map((ingredient, index) => (
                  <li
                    key={index}
                    className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 border-b border-border-subtle py-3 text-body-sm"
                  >
                    <span>{ingredient.name}</span>
                    <strong className="text-right font-label">
                      {ingredient.amount == null
                        ? "Quantity unresolved"
                        : `${ingredient.amount} ${ingredient.unit}`}
                    </strong>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-space-sm text-body-sm text-secondary">
              Recipe amounts for cooking. Verified buy quantities stay in the
              basket.
            </p>
          </section>
          <section aria-label="Cooking steps">
            <h3 className="m-0 mb-space-sm font-label text-label-md font-bold uppercase tracking-wider text-secondary">
              Steps
            </h3>
            {steps.length === 0 ? (
              <p className="m-0 text-body-sm text-secondary">
                No cooking steps in this plan.
              </p>
            ) : (
              <ol className="m-0 list-decimal space-y-space-sm pl-space-md text-body-sm text-on-surface">
                {steps.map((step, index) => (
                  <li key={index} className="pl-space-xs">
                    {step}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </div>,
    document.body,
  );
}
