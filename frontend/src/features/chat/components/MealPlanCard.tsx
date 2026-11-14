import type { MealPlan } from "../../../shared/api/types";
export function MealPlanCard({ plan }: { plan: MealPlan }) {
  return (
    <section className="meal-plan" aria-label="Proposed meal plan">
      <h2>{plan.title}</h2>
      <p>{plan.portions} portions</p>
      <p className="muted small">
        {plan.recipe_plan_id
          ? "Saved recipe plan"
          : "Free-form plan — recipe completeness not checked."}
      </p>
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
      {plan.attribution && <p className="muted small">{plan.attribution}</p>}
      {(plan.notes ?? []).map((note, i) => (
        <p className="muted small" key={i}>
          {note}
        </p>
      ))}
      <p className="muted small">
        Recipe quantities are a proposal. Verified quantities and purchasing
        checks appear in the basket.
      </p>
    </section>
  );
}
