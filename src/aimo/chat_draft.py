"""Small display projection of selected ingredients, never search candidates or authority."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from aimo.chat_schemas import DraftCart, DraftCartItem, DraftPrice, Ingredient, MealPlan

TRUSTED_PLAN_TITLE = "Your order"


def trusted_plan(session):
    """The purchasable facts of a plan whose model-written wording failed output review.

    Keeps only lines whose product the server read this turn, named by the catalog name, with the
    amount and unit the basket math uses. Every model-written text (title, notes, instructions,
    ingredient names, reasons, rejected choices) is dropped, so nothing unreviewed is shown; the
    basket built from it still passes every deterministic purchase rule and needs confirmation.
    Saved recipe plans and plans restored from an earlier turn are not projected."""
    plan = session.plan
    if not plan or plan.recipe_plan_id or plan == session.restored:
        return None
    items = []
    for item in plan.ingredients:
        name = session.products.get(item.product_id, {}).get("name") if item.product_id else None
        if not isinstance(name, str) or not name.strip():
            continue
        items.append(
            Ingredient(
                name=name.strip()[:240],
                amount=item.amount,
                unit=item.unit,
                product_id=item.product_id,
                ingredient_id=item.ingredient_id,
                status=item.status,
                purchase_amount=item.purchase_amount,
                purchase_unit=item.purchase_unit,
                product_fingerprint=item.product_fingerprint,
                conversion=item.conversion,
            )
        )
    if not items:
        return None
    return MealPlan(title=TRUSTED_PLAN_TITLE, portions=plan.portions, ingredients=items)


def cart_snapshot(session, *, plan_visible):
    if not session.plan or not plan_visible:
        return None
    items = []
    for ingredient in session.plan.ingredients:
        pid = ingredient.product_id
        matched = bool(pid) and (not session.plan.recipe_plan_id or ingredient.status == "matched")
        product = session.products.get(pid, {})
        evidence = session.commercial.get(pid)
        price = None
        # Display a checked price per SALES unit, not a guessed ingredient/line total.
        if (
            matched
            and evidence
            and pid in session.commercial_dates
            and evidence.get("mode") in ("fixture", "live")
            and not any(r["severity"] in ("unresolved", "denied") for r in evidence["reasons"])
        ):
            checked = (
                DraftPrice.model_validate(
                    {
                        key: evidence[key]
                        for key in (
                            "gross",
                            "currency",
                            "sales_unit",
                            "mode",
                            "observed_at",
                            "expires_at",
                        )
                    }
                    | {"delivery_date": session.commercial_dates[pid]}
                )
                if all(evidence.get(key) is not None for key in ("gross", "currency", "sales_unit"))
                else None
            )
            try:
                valid_amount = (
                    checked and Decimal(checked.gross).is_finite() and Decimal(checked.gross) >= 0
                )
            except InvalidOperation:
                valid_amount = False
            if (
                checked
                and valid_amount
                and evidence.get("price_basis") == "per_sales_unit"
                and checked.expires_at > datetime.now(timezone.utc)
            ):
                price = checked
        items.append(
            DraftCartItem(
                name=ingredient.name,
                amount=ingredient.purchase_amount
                if matched and ingredient.purchase_amount
                else ingredient.amount,
                unit=ingredient.purchase_unit
                if matched and ingredient.purchase_unit
                else ingredient.unit,
                product_id=pid if matched else None,
                product_name=product.get("name") if matched else None,
                matched=matched,
                price=price,
            )
        )
    return DraftCart(
        turn_id=str(session.identity["_turn_id"]),
        title=session.plan.title,
        items=items,
        proposal_id=session.proposal["proposal_id"] if session.prepared_digest else None,
    )
