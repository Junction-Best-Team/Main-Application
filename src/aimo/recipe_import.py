"""Explicit, resumable recipe import. Never called on startup or by agent tools."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from aimo import recipe_search
from aimo.db import Problem, connection, fingerprint, js
from aimo.recipe_schemas import ProductEvidence, Recipe
from aimo.search import dimensions, vector


def english(value):
    return value.get("en", "") if isinstance(value, dict) else value or ""


def normalize(raw, review=None):
    review = review or {}
    if set(review) - {"ingredients"}:
        raise ValueError("Unsupported recipe review field")
    overrides = review.get("ingredients", {})
    ingredients = []
    seen = set()
    for row in raw["ingredients"]:
        iid = row["id"]
        if iid in seen:
            raise ValueError("Duplicate ingredient ID; resolve source ambiguity before import")
        seen.add(iid)
        extra = overrides.get(iid, {})
        if set(extra) - {"form", "quantity", "unit", "scaling", "note"}:
            raise ValueError("Unsupported reviewed ingredient field")
        ingredients.append(
            dict(
                id=iid,
                name=english(row["name"]),
                quantity=row["quantity"],
                unit=row["unit"],
                scaling=row["scaling"],
                note=english(row.get("note")) or None,
            )
            | extra
        )
    if set(overrides) - seen:
        raise ValueError("Review refers to an unknown ingredient")
    return Recipe(
        id="unitools:" + raw["slug"],
        title=english(raw["name"]),
        summary=english(raw.get("summary")),
        base_servings=raw["baseServings"],
        category=raw["category"],
        ingredients=ingredients,
        instructions=[english(s["text"]) for s in raw["steps"]],
    )


def ingest_recipes(path: Path, expected_sha256: str, review_path: Path | None = None):
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValueError("Recipe file checksum differs from the explicitly selected snapshot")
    data = json.loads(content)
    if (
        data.get("license") != "CC BY-SA 4.0"
        or not data.get("attribution")
        or not data.get("version")
    ):
        raise ValueError("Expected attributed, versioned UniTools CC BY-SA 4.0 dataset")
    reviews = json.loads(review_path.read_text()) if review_path else {}
    if reviews and (not reviews.get("source") or set(reviews) - {"source", "recipes"}):
        raise ValueError("Reviewed overrides require source attribution")
    records = [
        (normalize(r, reviews.get("recipes", {}).get(r["slug"])), r) for r in data["recipes"]
    ]
    if not records or len(records) > 10000 or len({r.id for r, _ in records}) != len(records):
        raise ValueError("Invalid recipe count or duplicate recipe IDs")
    slugs = {r["slug"] for _, r in records}
    if set(reviews.get("recipes", {})) - slugs:
        raise ValueError("Review refers to an unknown recipe")
    key = recipe_search.model_key()
    docs = {r.id: recipe_search.text(r) for r, _ in records}
    hashes = {rid: fingerprint(t) for rid, t in docs.items()}
    # Persist each successful batch independently, so paid work survives a later failure.
    dim = dimensions()
    with connection() as c:
        cached = {
            r["text_hash"]
            for r in c.execute(
                "SELECT text_hash FROM recipe_embedding_cache WHERE model_key=%s AND vector_dims(embedding)=%s",
                (key, dim),
            )
        }
    pending = list(dict.fromkeys(h for h in hashes.values() if h not in cached))
    texts = {hashes[rid]: t for rid, t in docs.items()}
    for start in range(0, len(pending), 32):
        batch = pending[start : start + 32]
        values = recipe_search.embeddings([texts[h] for h in batch])
        with connection() as c:
            for h, value in zip(batch, values, strict=True):
                c.execute(
                    """INSERT INTO recipe_embedding_cache VALUES(%s,%s,%s::vector)
                    ON CONFLICT(model_key,text_hash) DO UPDATE SET embedding=excluded.embedding""",
                    (key, h, vector(value)),
                )
    generation = uuid4()
    source_hash = fingerprint({"dataset": digest, "review": reviews})
    with connection() as c:
        c.execute("SELECT pg_advisory_xact_lock(893019)")
        current = c.execute(
            """SELECT g.* FROM recipe_catalogs g JOIN active_recipe_catalog a
            ON a.catalog_id=g.id WHERE g.source_hash=%s AND g.model_key=%s""",
            (source_hash, key),
        ).fetchone()
        if current:
            return {
                "catalog_id": str(current["id"]),
                "recipes": len(records),
                "embedded": 0,
                "reused": len(records),
                "unchanged": True,
            }
        c.execute(
            "INSERT INTO recipe_catalogs(id,source_hash,model_key,dimensions,recipe_count) VALUES(%s,%s,%s,%s,%s)",
            (generation, source_hash, key, dim, len(records)),
        )
        for recipe, raw in records:
            value = recipe.model_dump(mode="json")
            value["review_source"] = reviews.get("source")
            value["original"] = raw
            version = fingerprint(
                {
                    "recipe": value,
                    "source_version": data["version"],
                    "attribution": data["attribution"],
                    "license": data["license"],
                }
            )
            c.execute("INSERT INTO recipes VALUES(%s) ON CONFLICT DO NOTHING", (recipe.id,))
            c.execute(
                """INSERT INTO recipe_versions(recipe_id,version,data,source,source_version,source_hash,attribution,license)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    recipe.id,
                    version,
                    js(value),
                    data.get("homepage", "UniTools"),
                    data["version"],
                    digest,
                    data["attribution"],
                    data["license"],
                ),
            )
            for ordinal, ingredient in enumerate(recipe.ingredients):
                c.execute(
                    "INSERT INTO recipe_ingredients VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        recipe.id,
                        version,
                        ingredient.id,
                        ordinal,
                        js(ingredient.model_dump(mode="json")),
                    ),
                )
            inserted = c.execute(
                """INSERT INTO recipe_catalog_entries(catalog_id,recipe_id,version,search_text,embedding)
                SELECT %s,%s,%s,%s,embedding FROM recipe_embedding_cache
                WHERE model_key=%s AND text_hash=%s AND vector_dims(embedding)=%s RETURNING recipe_id""",
                (generation, recipe.id, version, docs[recipe.id], key, hashes[recipe.id], dim),
            ).fetchone()
            if not inserted:
                raise Problem(
                    "RECIPE_EMBEDDING_INVALID", "Cached recipe vector has incorrect dimensions."
                )
        c.execute(
            "INSERT INTO active_recipe_catalog VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET catalog_id=excluded.catalog_id",
            (generation,),
        )
    return {
        "catalog_id": str(generation),
        "recipes": len(records),
        "embedded": len(pending),
        "reused": len(records) - len(pending),
        "unchanged": False,
    }


def import_product_evidence(path):
    """Privileged reviewed annotation import; never available as a model tool."""
    rows = [ProductEvidence.model_validate(r) for r in json.loads(path.read_text())]
    from aimo.purchases import load_products

    with connection() as c:
        products = load_products(c, [r.product_id for r in rows])
        for row in rows:
            if fingerprint(products.get(row.product_id)) != row.product_fingerprint:
                raise ValueError("Product annotation does not match current catalog facts")
            c.execute(
                """INSERT INTO recipe_product_evidence VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(product_id,product_fingerprint,ingredient_id,form)
                DO UPDATE SET source=excluded.source,piece_per_sales=excluded.piece_per_sales""",
                (
                    row.product_id,
                    row.product_fingerprint,
                    row.ingredient_id,
                    row.form,
                    row.source,
                    row.piece_per_sales,
                ),
            )
    return {"annotations": len(rows)}
