"""Supplier substitution rules as candidates (DIS-010). Candidates only, never a suitability claim.

The supplier lists, per product, `substitutions: [{"product": id, "substituteProduct": id}]`. The
rules are sparse and imperfect (self-substitutions, targets that are gone, allergen, unit or category
changes), so every target is re-read from the active catalog and shown with a `checks` block; the
caller and the buyer's policy decide. Buyer-list candidates are not supplied yet (POL-012 deferred).
"""

from aimo.db import connection
from aimo.purchases import context, load_products
from aimo.search import get_product

SUMMARY = (
    "id",
    "name",
    "names",
    "sales_unit",
    "base_unit",
    "units",
    "order_step",
    "measures",
    "claims",
    "allergens",
    "free_from",
    "provenance",
)


def checks(original: dict, target: dict) -> dict:
    """Differences the caller must weigh; none of them is a verdict."""
    return {
        "exists": True,
        "not_withdrawn": True,
        "sales_unit_differs": target["sales_unit"] != original["sales_unit"],
        "category_differs": target["category"] != original["category"],
        "allergens_added": sorted(set(target["allergens"]) - set(original["allergens"])),
        "claims_missing": sorted(set(original["claims"]) - set(target["claims"])),
    }


def list_substitution_candidates(identity, product_id, delivery_date=None):
    """Supplier-rule substitutes for `product_id`, in rule order, re-checked against the catalog.

    Availability is not decided here: the caller asks because the product is unavailable or outside
    the buyer's scope. `delivery_date` is accepted for the tool signature and not used.
    """
    original = get_product(identity, product_id)  # NOT_FOUND for a product not in the catalog
    targets, seen, excluded = [], set(), []
    for rule in original["substitutions"]:
        if not isinstance(rule, dict) or rule.get("product", product_id) != product_id:
            continue
        target = rule.get("substituteProduct")
        if target == product_id:
            excluded.append({"product_id": target, "reason": "self_substitution"})
        elif isinstance(target, str) and target not in seen:
            seen.add(target)
            targets.append(target)
    with connection() as c:
        context(c, identity)
        found = load_products(c, targets)
    candidates = []
    for target in targets:
        facts = found.get(target)
        if facts is None:
            excluded.append({"product_id": target, "reason": "not_in_active_catalog"})
        elif facts["deleted"]:
            excluded.append({"product_id": target, "reason": "withdrawn"})
        else:
            candidates.append(
                {k: facts[k] for k in SUMMARY}
                | {
                    "source": "supplier_rule",
                    "rule": {"product": product_id, "substituteProduct": target},
                    "checks": checks(original, facts),
                    "match_is_suitability_proof": False,
                }
            )
    return {
        "product_id": product_id,
        "candidates": candidates,
        "excluded": excluded,
        "note": "Supplier rules are candidates only. Check claims, allergens, unit and category, "
        "current price and availability, and the buyer's substitution policy before use.",
    }
