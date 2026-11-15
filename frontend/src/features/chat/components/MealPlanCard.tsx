import type { MealPlan } from "../../../shared/api/types";
export function MealPlanCard({
  plan,
  compact = false,
}: {
  plan: MealPlan;
  compact?: boolean;
}) {
  const details = (
    <>
      <ul>
        {plan.ingredients.map((ingredient, i) => (
          <li key={i}>
            <span>{ingredient.name}</span>
            <strong>
              {ingredient.amount == null
                ? "Quantity unresolved"
                : `${ingredient.amount} ${ingredient.unit}`}
            </strong>
            {ingredient.status === "unresolved" && <p>{ingredient.reason}</p>}
            {ingredient.product_id && <p>Product: {ingredient.product_id}</p>}
            {ingredient.conversion?.sales_quantity && (
              <p>
                Buy {String(ingredient.conversion.sales_quantity)}{" "}
                {String(ingredient.conversion.sales_unit)}
                {Number(ingredient.conversion.excess) > 0 &&
                  ` · Excess: ${ingredient.conversion.excess} ${ingredient.unit}`}
              </p>
            )}
          </li>
        ))}
      </ul>
      {plan.attribution && (
        <p className="text-body-sm text-secondary">{plan.attribution}</p>
      )}
      {(plan.notes ?? []).map((note, i) => (
        <p className="text-body-sm text-secondary" key={i}>
          {note}
        </p>
      ))}
      <p className="text-body-sm text-secondary">
        Recipe quantities are a proposal. Verified quantities and purchasing
        checks appear in the basket.
      </p>
    </>
  );
  return (
    <section
      className="meal-plan mt-4 max-w-[660px] rounded-lg border border-border-subtle bg-surface-pure p-4 text-on-surface md:p-5 [&_h2]:text-headline-sm [&_ul]:my-4 [&_ul]:list-none [&_ul]:p-0 [&_li]:grid [&_li]:grid-cols-[minmax(0,1fr)_auto] [&_li]:gap-x-4 [&_li]:gap-y-1 [&_li]:border-b [&_li]:border-border-subtle [&_li]:py-3 [&_li]:text-body-sm [&_li>strong]:text-right [&_li>strong]:font-label [&_li>p]:col-span-2 [&_li>p]:m-0 [&_li>p]:text-secondary [&>p:last-child]:mb-0"
      aria-label="Proposed meal plan"
    >
      <h2>{plan.title}</h2>
      <p>{plan.portions} portions</p>
      <p className="text-body-sm text-secondary">
        {plan.recipe_plan_id
          ? "Saved recipe plan"
          : "Free-form plan — recipe completeness not checked."}
      </p>
      {compact ? (
        <details className="mt-space-sm">
          <summary className="cursor-pointer font-label text-label-md text-primary">
            Recipe quantities and assumptions
          </summary>
          {details}
        </details>
      ) : (
        details
      )}
    </section>
  );
}
