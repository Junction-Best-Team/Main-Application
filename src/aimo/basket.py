"""Which ingredients a basket line serves, and each one's exact share of what is bought.

MEA-005 / MEA-009 / BAS-002: one product can serve several ingredients, so its line is a sum.
The purchased amount (whole packs, with excess) is split across the ingredients in proportion to
what each needs, with exact Fraction arithmetic, so the shares add up to the line exactly.
"""

from fractions import Fraction

from aimo.numeric import fraction_text


def exact_text(value: Fraction) -> str:
    """Decimal text when it terminates, else "numerator/denominator"; never a rounded value."""
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return fraction_text(value) if d == 1 else f"{value.numerator}/{value.denominator}"


def allocate_line(quantity: dict, parts: list[dict]) -> list[dict]:
    """Contributions of `parts` ({ingredient, ingredient_id, amount, unit}) to one basket line.

    Each part keeps its required amount. When the line's purchase is known and every part is in
    the line's unit, it also gets its share of the purchased amount, of the excess and of the
    sales quantity, proportional to its required amount; the shares sum exactly to the line.
    """
    result = [
        {key: part.get(key) for key in ("ingredient", "ingredient_id", "amount", "unit")}
        for part in parts
    ]
    proposed = quantity.get("proposed_amount")
    needs = [Fraction(part["amount"]) for part in parts]
    if proposed is None or not parts or any(p["unit"] != quantity["requested_unit"] for p in parts):
        return result
    weight = sum(needs)
    for name, key in (
        ("purchased_amount", "proposed_amount"),
        ("excess", "excess"),
        ("sales_quantity", "sales_quantity"),
    ):
        if quantity.get(key) is not None:
            whole = Fraction(quantity[key])
            for item, need in zip(result, needs):
                item[name] = exact_text(whole * need / weight)
    return result


def line_contributions(request, plan: dict | None) -> dict[str, list[dict]]:
    """Contribution inputs per product ID: from the saved plan, else from the request lines."""
    on_basket = {line.product_id for line in request.lines}
    found: dict[str, list[dict]] = {}
    if plan is not None:
        for item in plan["ingredients"]:
            if item.get("product_id") in on_basket and item.get("purchase_amount"):
                found.setdefault(item["product_id"], []).append(
                    {
                        "ingredient": item["name"],
                        "ingredient_id": item.get("ingredient_id"),
                        "amount": item["purchase_amount"],
                        "unit": item["purchase_unit"],
                    }
                )
        return found
    for line in request.lines:
        if line.contributions:
            found[line.product_id] = [c.model_dump(mode="json") for c in line.contributions]
    return found
