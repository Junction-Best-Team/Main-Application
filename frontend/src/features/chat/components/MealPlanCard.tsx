import { useState } from "react";
import type { MealPlan } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { RecipeOverlay } from "./RecipeOverlay";

/** Compact recipe teaser; opens the fullscreen ingredients/steps overlay. */
export function MealPlanCard({ plan }: { plan: MealPlan }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="meal-plan mt-4 flex w-full max-w-[660px] cursor-pointer items-start gap-space-sm rounded-lg border border-border-subtle bg-surface-pure p-4 text-left text-on-surface transition-colors hover:bg-surface-container-low md:p-5"
        aria-label={`Open recipe ${plan.title}`}
      >
        <Icon
          name="menu_book"
          className="mt-0.5 text-[22px] text-wholesale-teal"
        />
        <span className="min-w-0 flex-1">
          <span className="block font-headline text-headline-sm text-primary">
            {plan.title}
          </span>
          <span className="mt-1 block text-body-sm text-secondary">
            {plan.portions} portions · Tap for ingredients and steps
          </span>
        </span>
        <Icon name="chevron_right" className="mt-1 text-[20px] text-secondary" />
      </button>
      {open && (
        <RecipeOverlay plan={plan} onClose={() => setOpen(false)} />
      )}
    </>
  );
}
