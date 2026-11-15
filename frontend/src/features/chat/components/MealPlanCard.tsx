import type { MealPlan } from "../../../shared/api/types";

const boilerplateNotes = new Set([
  "Recipe quantities are estimates for customer review. All source ingredients remain required.",
  "Recipe quantities are estimates for customer review.",
  "Recipe quantities are estimates.",
]);

function ingredientIssue(ingredient: MealPlan["ingredients"][number]) {
  if (ingredient.amount == null)
    return "Quantity needs verification before purchasing.";
  if (ingredient.status !== "unresolved") return null;
  if (ingredient.form === "unspecified")
    return "The required ingredient form needs verification before purchasing.";
  // Older saved conversations contain an internal task rather than a customer explanation.
  if (ingredient.reason === "Match a suitable catalog product.") return null;
  if (
    ingredient.reason ===
    "No current reviewed evidence that this product fits the ingredient and form."
  )
    return "A suitable product has not been verified for this ingredient.";
  return ingredient.reason;
}

export function MealPlanCard({ plan }: { plan: MealPlan }) {
  return (
    <section
      className="meal-plan mt-4 max-w-[660px] rounded-lg border border-border-subtle bg-surface-pure p-4 text-on-surface md:p-5 [&_h2]:text-headline-sm [&_ul]:my-4 [&_ul]:list-none [&_ul]:p-0 [&_li]:grid [&_li]:grid-cols-[minmax(0,1fr)_auto] [&_li]:gap-x-4 [&_li]:gap-y-1 [&_li]:border-b [&_li]:border-border-subtle [&_li]:py-3 [&_li]:text-body-sm [&_li>strong]:text-right [&_li>strong]:font-label [&_li>p]:col-span-2 [&_li>p]:m-0 [&_li>p]:text-secondary [&>p:last-child]:mb-0"
      aria-label="Proposed meal plan"
    >
      <h2>{plan.title}</h2>
      <p>{plan.portions} portions</p>
      <p className="text-body-sm text-secondary">
        {plan.recipe_plan_id
          ? "Saved recipe · quantities are estimates"
          : "Free-form plan — recipe completeness not checked."}
      </p>
      {plan.ingredients.some((ingredient) => !ingredient.product_id) && (
        <p className="text-body-sm text-secondary">
          Product selection and purchasing checks are not complete.
        </p>
      )}
      <ul>
        {plan.ingredients.map((ingredient, i) => (
          <li key={i}>
            <span>{ingredient.name}</span>
            <strong
              className={
                ingredient.amount == null ? "col-span-2 text-left!" : undefined
              }
            >
              {ingredient.amount == null
                ? "Quantity needs verification"
                : `${ingredient.amount} ${ingredient.unit}`}
            </strong>
            {ingredientIssue(ingredient) && (
              <p>{ingredientIssue(ingredient)}</p>
            )}
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
        <details className="text-body-sm text-secondary">
          <summary className="cursor-pointer">Recipe source</summary>
          <p className="mt-2">{plan.attribution}</p>
        </details>
      )}
      {(plan.notes ?? [])
        .filter((note) => !boilerplateNotes.has(note.trim()))
        .map((note, i) => (
          <p className="text-body-sm text-secondary" key={i}>
            {note}
          </p>
        ))}
    </section>
  );
}
