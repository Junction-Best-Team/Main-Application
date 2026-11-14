"""MEA-014: match several recipe ingredients to catalog products in one call and one revision."""

from decimal import Decimal

from pydantic import Field

from aimo.catalog import quantity
from aimo.db import Problem, connection, fingerprint, js
from aimo.purchases import context, load_products
from aimo.recipe_schemas import PlanReference
from aimo.recipes import read_plan
from aimo.schemas import MAX_BASKET_LINES, Model

MAX_BATCH_MATCHES = MAX_BASKET_LINES  # MEA-013: a plan has at most 100 ingredients.


class IngredientMatch(Model):
    ingredient_id: str = Field(min_length=1, max_length=120)
    product_id: str = Field(min_length=1, max_length=40)


class MatchIngredients(PlanReference):
    revision: int = Field(ge=1)
    matches: list[IngredientMatch] = Field(min_length=1, max_length=MAX_BATCH_MATCHES)


def match_ingredients(identity, request):
    """Match every pair against the saved plan and write exactly one new plan revision.

    All-or-nothing: any invalid pair raises inside the transaction, so nothing is written.
    """
    with connection() as c:
        _, policy, _, _ = context(c, identity)
        row, plan = read_plan(c, identity, request.plan_id, lock=True)
        if row["locked"]:
            raise Problem(
                "RECIPE_PLAN_LOCKED", "This plan already has a prepared basket; create a new plan."
            )
        if row["revision"] != request.revision:
            raise Problem("RECIPE_PLAN_CHANGED", "Reload the current recipe plan before matching.")
        items = {i["ingredient_id"]: i for i in plan["ingredients"]}
        seen = set()
        for pair in request.matches:
            if pair.ingredient_id not in items:
                raise Problem("INGREDIENT_UNKNOWN", "Ingredient is not part of this recipe.", 422)
            if pair.ingredient_id in seen:
                raise Problem(
                    "INGREDIENT_DUPLICATE",
                    "An ingredient appears more than once in the batch.",
                    422,
                )
            seen.add(pair.ingredient_id)
        products = load_products(c, sorted({m.product_id for m in request.matches}))
        for pair in request.matches:
            item = items[pair.ingredient_id]
            _match(c, policy, item, products.get(pair.product_id), pair)
            _record_rejection(item, pair.product_id)
        plan["recipe_plan_revision"] = row["revision"] + 1
        c.execute(
            "INSERT INTO recipe_plan_revisions VALUES(%s,%s,%s,now())",
            (row["id"], plan["recipe_plan_revision"], js(plan)),
        )
        c.execute(
            "UPDATE recipe_plans SET revision=%s WHERE id=%s",
            (plan["recipe_plan_revision"], row["id"]),
        )
    return plan


def _record_rejection(item, product_id):
    """MEA-005: keep a refused product choice (appended, never removed) with its reason."""
    if item["status"] == "unresolved" and item["amount"] and item.get("reason"):
        item.setdefault("rejected", []).append({"product_id": product_id, "reason": item["reason"]})


# Mirrors recipes.match_ingredient; keep in sync or refactor (see MEA-014-requests.md).
def _match(c, policy, item, p, pair):
    evidence = c.execute(
        """SELECT * FROM recipe_product_evidence WHERE product_id=%s
        AND product_fingerprint=%s AND ingredient_id=%s AND form=%s""",
        (pair.product_id, fingerprint(p), item["ingredient_id"], item["form"]),
    ).fetchone()
    item.update(
        product_id=None,
        purchase_amount=None,
        purchase_unit=None,
        product_fingerprint=None,
        conversion=None,
        status="unresolved",
    )
    if not item["amount"]:
        return  # Preserve the scaling/unit blocker.
    if item["form"] == "unspecified":
        item["reason"] = "Review the required ingredient form before product matching."
    elif not p or p["deleted"]:
        item["reason"] = "Product is absent or withdrawn."
    elif not evidence:
        item["reason"] = (
            "No current reviewed evidence that this product fits the ingredient and form."
        )
    else:
        amount, unit = Decimal(item["amount"]), item["unit"]
        if unit == "piece" and not evidence["piece_per_sales"]:
            item["reason"] = "Verified ingredient count per sales unit is missing."
            q = None
        else:
            q = quantity(
                p,
                amount,
                unit,
                policy["rules"].get("whole_sales_units", True),
                count_evidence=evidence if unit == "piece" else None,
            )
        if q and q["sales_quantity"]:
            item.update(
                product_id=p["id"],
                status="matched",
                reason=None,
                purchase_amount=str(amount),
                purchase_unit=unit,
                product_fingerprint=fingerprint(p),
                conversion=q,
            )
        elif q:
            item["reason"] = (
                "Structured product data cannot convert the ingredient quantity into sales units."
            )
