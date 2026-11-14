"""Recipe discovery and server-owned scaling, matching and complete-basket validation."""

from decimal import Decimal
from fractions import Fraction
from uuid import uuid4

from aimo import recipe_search
from aimo.catalog import quantity
from aimo.chat_schemas import MealPlan
from aimo.db import Problem, connection, fingerprint, js
from aimo.numeric import fraction_text
from aimo.purchases import context, load_products
from aimo.recipe_schemas import Recipe
from aimo.search import vector


def recipe_value(data):
    return Recipe.model_validate({k: v for k, v in data.items() if k in Recipe.model_fields})


def search_recipes(identity, request):
    with connection() as c:
        context(c, identity)
        active = c.execute(
            "SELECT g.* FROM recipe_catalogs g JOIN active_recipe_catalog a ON a.catalog_id=g.id"
        ).fetchone()
        if not active:
            raise Problem("RECIPES_NOT_READY", "Recipe data has not been imported yet.", 503)
        if active["model_key"] != recipe_search.model_key():
            raise Problem(
                "RECIPE_MODEL_MISMATCH",
                "Import recipes with the configured recipe search profile.",
                503,
            )
    query_vector = vector(recipe_search.embeddings([request.query], query=True)[0])
    with connection() as c:
        context(c, identity)
        rows = c.execute(
            """SELECT e.recipe_id,e.version,e.search_text,v.data,
            ts_rank_cd(e.search_document,plainto_tsquery('english',%s)) AS keyword,
            CASE WHEN vector_dims(e.embedding)=%s THEN e.embedding <=> %s::vector END AS distance
            FROM recipe_catalog_entries e JOIN recipe_versions v
            ON v.recipe_id=e.recipe_id AND v.version=e.version
            WHERE e.catalog_id=%s AND (%s::text IS NULL OR v.data->>'category'=%s)""",
            (
                request.query,
                active["dimensions"],
                query_vector,
                active["id"],
                request.category,
                request.category,
            ),
        ).fetchall()
    scores = {}
    for ranking in [
        sorted(
            rows, key=lambda r: (r["distance"] if r["distance"] is not None else 2, r["recipe_id"])
        ),
        sorted(
            [r for r in rows if r["keyword"] > 0], key=lambda r: (-r["keyword"], r["recipe_id"])
        ),
    ]:
        for i, row in enumerate(ranking):
            scores[row["recipe_id"]] = scores.get(row["recipe_id"], 0) + 1 / (61 + i)
    ranked = sorted(rows, key=lambda r: (-scores.get(r["recipe_id"], 0), r["recipe_id"]))
    rerank_status = "disabled"
    if recipe_search.hosted() and ranked:
        from aimo.config import settings

        if settings().rerank_enabled:
            from aimo.search_provider import rerank

            shortlist = ranked[: settings().rerank_candidates]
            try:
                positions = rerank(
                    "Find cooking recipes for: " + request.query,
                    [r["search_text"] for r in shortlist],
                )
                ranked = [shortlist[i] for i, _ in positions]
                rerank_status = "applied"
            except Problem:
                rerank_status = "unavailable"
    return {
        "recipes": [
            {
                "recipe_id": r["recipe_id"],
                "version": r["version"],
                "title": r["data"]["title"],
                "summary": r["data"]["summary"],
                "base_servings": r["data"]["base_servings"],
            }
            for r in ranked[: request.limit]
        ],
        "rerank_status": rerank_status,
        "note": "Recipe ideas only; dietary suitability and purchasable quantities require evidence.",
    }


def get_recipe(identity, request):
    with connection() as c:
        context(c, identity)
        row = c.execute(
            "SELECT * FROM recipe_versions WHERE recipe_id=%s AND version=%s",
            (request.recipe_id, request.version),
        ).fetchone()
    if not row:
        raise Problem("NOT_FOUND", "Recipe version not found.", 404)
    return {
        "recipe": recipe_value(row["data"]).model_dump(mode="json"),
        "version": row["version"],
        "source": row["source"],
        "attribution": row["attribution"],
        "license": row["license"],
    }


def scaled_plan(recipe, portions):
    if len(recipe.ingredients) > 30:
        raise Problem(
            "RECIPE_TOO_LARGE", "This recipe exceeds the 30-ingredient purchasing limit.", 422
        )
    ingredients = []
    for item in recipe.ingredients:
        amount, unit, reason = None, item.unit, "Match a suitable catalog product."
        if item.quantity is None:
            reason = "Recipe quantity is unspecified; provide a reviewed numeric quantity."
        elif item.scaling != "linear":
            reason = "This ingredient needs a reviewed scaling rule for the requested portions."
        else:
            value = Fraction(item.quantity) * portions / recipe.base_servings
            factors = {
                "g": (Fraction(1, 1000), "KG"),
                "kg": (Fraction(1), "KG"),
                "ml": (Fraction(1, 1000), "L"),
                "l": (Fraction(1), "L"),
                "piece": (Fraction(1), "piece"),
            }
            if unit in factors:
                factor, unit = factors[unit]
                # The purchasing contract allows at most four decimal places; never silently round.
                value *= factor
                amount = fraction_text(value)
                if (
                    Decimal(amount).as_tuple().exponent < -4
                    or len(Decimal(amount).as_tuple().digits) > 14
                ):
                    amount = None
                    reason = "Scaled quantity exceeds supported precision; review the recipe basis."
            else:
                reason = (
                    "Recipe unit needs an ingredient-specific conversion to mass, volume or count."
                )
        ingredients.append(
            dict(
                name=item.name,
                ingredient_id=item.id,
                amount=amount,
                unit=unit,
                form=item.form,
                status="unresolved",
                reason=reason,
            )
        )
    return MealPlan(
        title=recipe.title,
        portions=portions,
        ingredients=ingredients,
        base_servings=recipe.base_servings,
        notes=[
            "Recipe quantities are estimates for customer review. All source ingredients remain required."
        ],
    )


def scale_recipe(identity, request):
    if not identity.get("_turn_id"):
        raise Problem("TURN_CONTEXT_REQUIRED", "A persisted turn is required.", 422)
    detail = get_recipe(identity, request)
    plan = scaled_plan(Recipe.model_validate(detail["recipe"]), request.portions)
    plan.recipe_id, plan.recipe_version = request.recipe_id, request.version
    plan.attribution = detail["attribution"] + " / " + detail["license"]
    with connection() as c:
        context(c, identity)
        c.execute("SELECT pg_advisory_xact_lock(893020)")
        existing = c.execute(
            "SELECT * FROM recipe_plans WHERE buyer_id=%s AND agent_id=%s AND turn_id=%s",
            (identity["buyer_id"], identity["id"], identity["_turn_id"]),
        ).fetchone()
        if existing:
            if (existing["recipe_id"], existing["recipe_version"], existing["portions"]) != (
                request.recipe_id,
                request.version,
                request.portions,
            ):
                raise Problem(
                    "RECIPE_PLAN_LOCKED", "Change the recipe or portions in a new customer message."
                )
            return read_plan(c, identity, existing["id"])[1]
        pid = uuid4()
        plan.recipe_plan_id, plan.recipe_plan_revision = str(pid), 1
        data = plan.model_dump(mode="json")
        c.execute(
            "INSERT INTO recipe_plans(id,buyer_id,agent_id,turn_id,recipe_id,recipe_version,portions) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                pid,
                identity["buyer_id"],
                identity["id"],
                identity["_turn_id"],
                request.recipe_id,
                request.version,
                request.portions,
            ),
        )
        c.execute("INSERT INTO recipe_plan_revisions VALUES(%s,1,%s,now())", (pid, js(data)))
    return data


def read_plan(c, identity, plan_id, lock=False):
    row = c.execute(
        "SELECT * FROM recipe_plans WHERE id=%s AND buyer_id=%s AND agent_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (plan_id, identity["buyer_id"], identity["id"]),
    ).fetchone()
    if not row:
        raise Problem("NOT_FOUND", "Recipe plan not found.", 404)
    data = c.execute(
        "SELECT data FROM recipe_plan_revisions WHERE plan_id=%s AND revision=%s",
        (plan_id, row["revision"]),
    ).fetchone()["data"]
    return row, data


def get_plan(identity, request):
    with connection() as c:
        context(c, identity)
        return read_plan(c, identity, request.plan_id)[1]


def match_ingredient(identity, request):
    with connection() as c:
        _, policy, _, _ = context(c, identity)
        row, plan = read_plan(c, identity, request.plan_id, lock=True)
        if row["locked"]:
            raise Problem(
                "RECIPE_PLAN_LOCKED", "This plan already has a prepared basket; create a new plan."
            )
        if row["revision"] != request.revision:
            raise Problem("RECIPE_PLAN_CHANGED", "Reload the current recipe plan before matching.")
        item = next(
            (i for i in plan["ingredients"] if i["ingredient_id"] == request.ingredient_id), None
        )
        if not item:
            raise Problem("INGREDIENT_UNKNOWN", "Ingredient is not part of this recipe.", 422)
        p = load_products(c, [request.product_id]).get(request.product_id)
        evidence = c.execute(
            """SELECT * FROM recipe_product_evidence WHERE product_id=%s
            AND product_fingerprint=%s AND ingredient_id=%s AND form=%s""",
            (request.product_id, fingerprint(p), item["ingredient_id"], item["form"]),
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
            pass  # Preserve the scaling/unit blocker.
        elif item["form"] == "unspecified":
            item["reason"] = "Review the required ingredient form before product matching."
        elif not p or p["deleted"] or p["variable_weight"]:
            item["reason"] = "Product is absent, withdrawn or has unresolved variable weight."
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


def validate_basket(c, identity, request):
    row, plan = read_plan(c, identity, request.recipe_plan_id, lock=True)
    if row["locked"]:
        raise Problem(
            "RECIPE_PLAN_LOCKED",
            "This plan already has a prepared basket; read the existing proposal.",
        )
    if row["revision"] != request.recipe_plan_revision:
        raise Problem("RECIPE_PLAN_CHANGED", "Prepare the current recipe plan revision.")
    if any(i["status"] != "matched" for i in plan["ingredients"]):
        raise Problem(
            "INCOMPLETE_MEAL_PLAN",
            "Resolve every recipe ingredient before preparing a basket.",
            422,
        )
    products = load_products(c, [i["product_id"] for i in plan["ingredients"]])
    required = {}
    for item in plan["ingredients"]:
        if fingerprint(products.get(item["product_id"])) != item["product_fingerprint"]:
            raise Problem("RECIPE_PRODUCT_CHANGED", "Catalog facts changed; rematch ingredients.")
        key = (item["product_id"], item["purchase_unit"])
        required[key] = required.get(key, Decimal(0)) + Decimal(item["purchase_amount"])
    actual = {(line.product_id, line.unit): line.amount for line in request.lines}
    if required != actual:
        raise Problem(
            "MEAL_BASKET_MISMATCH",
            "Basket must cover exactly the saved recipe ingredient quantities.",
            422,
        )
    purchase_count_evidence(c, identity, request, products)
    return row


def purchase_count_evidence(c, identity, request, products):
    """Re-read suitability and count evidence on preparation AND commit repricing."""
    if not request.recipe_plan_id:
        return {}
    _, plan = read_plan(c, identity, request.recipe_plan_id)
    if plan["recipe_plan_revision"] != request.recipe_plan_revision:
        raise Problem("RECIPE_PLAN_CHANGED", "Recipe revision changed; prepare again.")
    result = {}
    for item in plan["ingredients"]:
        pid = item["product_id"]
        evidence = c.execute(
            """SELECT * FROM recipe_product_evidence WHERE product_id=%s
            AND product_fingerprint=%s AND ingredient_id=%s AND form=%s""",
            (pid, fingerprint(products[pid]), item["ingredient_id"], item["form"]),
        ).fetchone()
        if not evidence:
            raise Problem(
                "RECIPE_PRODUCT_EVIDENCE_CHANGED",
                "Reviewed product suitability changed; create a new plan and rematch ingredients.",
            )
        if item["unit"] == "piece" and not evidence["piece_per_sales"]:
            raise Problem(
                "QUANTITY_UNRESOLVED", "Verified ingredient count is no longer available."
            )
        if item["unit"] == "piece":
            if pid in result and result[pid]["piece_per_sales"] != evidence["piece_per_sales"]:
                raise Problem(
                    "QUANTITY_UNRESOLVED", "One product has incompatible ingredient yields."
                )
            result[pid] = evidence
    return result
