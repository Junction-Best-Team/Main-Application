import { useEffect, useId, useRef } from "react";
import type { MealPlan } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { downloadRecipePdf } from "../model/recipePdf";

export function RecipeOverlay({
  plan,
  onClose,
  onOpenBasket,
}: {
  plan: MealPlan;
  onClose: () => void;
  onOpenBasket?: () => void;
}) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const steps = plan.instructions ?? [];

  useEffect(() => {
    const previous = document.activeElement;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key !== "Tab") return;
      const items = dialog.current?.querySelectorAll<HTMLElement>(
        "button:not(:disabled), a[href]",
      );
      const first = items?.[0];
      const last = items?.[items.length - 1];
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
      if (previous instanceof HTMLElement) previous.focus({ preventScroll: true });
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[80] flex items-end justify-center sm:items-center">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-deep-ocean-navy/45"
        onClick={onClose}
      />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative z-[1] flex max-h-[min(92dvh,880px)] w-full max-w-lg flex-col overflow-hidden rounded-t-xl bg-surface-pure shadow-level-3 sm:mx-space-md sm:rounded-xl"
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
              {plan.portions} portions
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
        <div className="min-h-0 flex-1 overflow-y-auto px-space-md py-space-md">
          <section aria-label="Ingredients" className="mb-space-lg">
            <h3 className="m-0 mb-space-sm font-label text-label-md font-bold uppercase tracking-wider text-secondary">
              Ingredients
            </h3>
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
            <p className="mt-space-sm text-body-sm text-secondary">
              Recipe amounts for cooking. Verified buy quantities stay in the
              basket.
            </p>
          </section>
          <section aria-label="Cooking steps">
            <h3 className="m-0 mb-space-sm font-label text-label-md font-bold uppercase tracking-wider text-secondary">
              Steps
            </h3>
            <ol className="m-0 list-decimal space-y-space-sm pl-space-md text-body-sm text-on-surface">
              {steps.map((step, index) => (
                <li key={index} className="pl-space-xs">
                  {step}
                </li>
              ))}
            </ol>
          </section>
        </div>
        <div className="flex shrink-0 justify-end gap-space-sm border-t border-border-subtle px-space-md py-space-sm">
          <button
            type="button"
            disabled={!onOpenBasket}
            onClick={() => onOpenBasket?.()}
            className="rounded-lg bg-surface-container px-space-md py-space-sm font-label text-label-md font-bold text-deep-ocean-navy transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
          >
            Open basket
          </button>
          <button
            type="button"
            onClick={() => downloadRecipePdf(plan)}
            className="inline-flex items-center gap-1 rounded-lg bg-primary-container px-space-md py-space-sm font-label text-label-md font-bold text-on-primary transition-colors hover:bg-deep-ocean-navy"
          >
            <Icon name="file_download" className="text-[18px]" />
            Download PDF
          </button>
        </div>
      </div>
    </div>
  );
}
