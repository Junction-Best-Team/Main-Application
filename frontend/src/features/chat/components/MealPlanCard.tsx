import { useState } from "react";
import type { MealPlan } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { mealPlanHasCookingSteps } from "../model/recipePdf";
import { RecipeOverlay } from "./RecipeOverlay";

/** Compact recipe-as-message; overlay only when catalog cooking steps exist. */
export function MealPlanCard({
  plan,
  onOpenBasket,
}: {
  plan: MealPlan;
  onOpenBasket?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const expandable = mealPlanHasCookingSteps(plan);

  return (
    <>
      {expandable ? (
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
      ) : (
        <section
          className="meal-plan mt-4 max-w-[660px] rounded-lg border border-border-subtle bg-surface-pure p-4 text-on-surface md:p-5"
          aria-label="Proposed meal plan"
        >
          <h2 className="font-headline text-headline-sm text-primary">
            {plan.title}
          </h2>
          <p className="m-0 text-body-sm text-secondary">
            {plan.portions} portions
            {plan.recipe_id
              ? " · Recipe quantities are in the basket"
              : " · Free-form plan — open the basket for ingredients"}
          </p>
        </section>
      )}
      {open && expandable && (
        <RecipeOverlay
          plan={plan}
          onClose={() => setOpen(false)}
          onOpenBasket={
            onOpenBasket
              ? () => {
                  setOpen(false);
                  onOpenBasket();
                }
              : undefined
          }
        />
      )}
    </>
  );
}
