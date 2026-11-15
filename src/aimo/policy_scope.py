"""Q-134 (a): the demo buyer's approved product scope as DATA.

`approved_product_ids` is a list (there is no "all products" form, and a missing list blocks every
purchase). To keep a normal meal basket in scope the seed, and the one-off script for buyers that are
already seeded, list every non-withdrawn product of the ACTIVE catalogue. No rule changes: a line the
agent declares as a substitution still needs approval, a product outside the catalogue is still
unknown, and the agent has no way to edit the policy.
"""

OLD_SCOPE = ["464306"]  # the original one-product demo scope


def catalog_product_ids(c):
    rows = c.execute(
        """SELECT p.id FROM products p JOIN active_catalog a ON p.generation=a.generation
        WHERE NOT coalesce((p.facts->>'deleted')::boolean, false) ORDER BY p.id"""
    ).fetchall()
    return [row["id"] for row in rows]


def widened_rules(rules, catalog_ids):
    """The same policy with the scope widened to the catalogue (never narrowed) and overbuy allowed."""
    scope = sorted(set(rules.get("approved_product_ids") or []) | set(catalog_ids))
    return {**rules, "approved_product_ids": scope, "overbuy": "allowed"}
