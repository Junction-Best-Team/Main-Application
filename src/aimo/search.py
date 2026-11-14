import hashlib
import math
import re
from functools import lru_cache

from aimo.catalog import requirement_reasons
from aimo.config import settings
from aimo.db import Problem, connection
from aimo.schemas import SearchRequest

PINNED_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


def model_key():
    cfg = settings()
    if cfg.embedding_backend == "fixture":
        return "fixture-hash-v1:384"
    return f"{cfg.embedding_model}@{cfg.embedding_model_revision or PINNED_REVISION}"


@lru_cache(maxsize=1)
def model():
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(4)
    cfg = settings()
    return SentenceTransformer(
        cfg.embedding_model,
        revision=cfg.embedding_model_revision or PINNED_REVISION,
        device="cpu",
        trust_remote_code=False,
    )


def embed(texts: list[str], query=False):
    if settings().embedding_backend == "fixture":
        rows = []
        for text in texts:
            values = [0.0] * 384
            for token in re.findall(r"\w+", text.lower()):
                slot = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % 384
                values[slot] += 1
            norm = math.sqrt(sum(x * x for x in values)) or 1
            rows.append([x / norm for x in values])
        return rows
    prefix = "query: " if query else "passage: "
    return (
        model()
        .encode(
            [prefix + t for t in texts],
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        .tolist()
    )


def vector(values):
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def get_product(identity, product_id):
    from aimo.purchases import context, load_products

    with connection() as c:
        context(c, identity)
        p = load_products(c, [product_id]).get(product_id)
    if not p:
        raise Problem("NOT_FOUND", "Product not found in the active catalog.", 404)
    return p


def search_products(identity, request: SearchRequest, strategy="hybrid"):
    from aimo.purchases import context

    with connection() as c:
        context(c, identity)
        active = c.execute(
            "SELECT g.* FROM active_catalog a JOIN catalog_generations g ON a.generation=g.id"
        ).fetchone()
        if not active:
            raise Problem("INDEX_NOT_READY", "Run ingestion before searching.", 503)
        if active["model_key"] != model_key():
            raise Problem(
                "MODEL_MISMATCH", "Serving model differs from the active catalog generation.", 503
            )
        where = "generation=%s AND jsonb_array_length(facts->'allergen_conflicts')=0"
        params = [active["id"]]
        if request.requirements.lactose_free:
            where += " AND facts->'claims' ? 'FREE_FROM_LACTOSE'"
        if request.requirements.milk_free:
            where += " AND facts->'free_from' ? 'AM' AND NOT facts->'allergens' ? 'AM'"
        exact = c.execute(
            f"SELECT id,facts FROM products WHERE {where} AND (id=%s OR gtin=%s)",
            (*params, request.query, request.query),
        ).fetchall()
        if request.query.isdigit() and not exact:
            return {
                "products": [],
                "generation": str(active["id"]),
                "model": active["model_key"],
                "strategy": strategy,
                "note": "Exact identifier absent or excluded by mandatory requirements.",
            }
        c.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        c.execute("SET LOCAL hnsw.ef_search = 200")
        keyword, semantic = [], []
        if strategy in ("keyword", "hybrid"):
            keyword = c.execute(
                f"""SELECT id,facts,ts_rank_cd(search_document,q) AS rank FROM products,
                (SELECT plainto_tsquery('simple',%s) || plainto_tsquery('finnish',%s) || plainto_tsquery('english',%s) q) query
                WHERE {where} AND search_document @@ q ORDER BY rank DESC,id LIMIT 80""",
                (request.query, request.query, request.query, *params),
            ).fetchall()
        if strategy in ("semantic", "hybrid"):
            v = vector(embed([request.query], query=True)[0])
            semantic = c.execute(
                f"SELECT id,facts,1-(embedding <=> %s::vector) AS similarity FROM products WHERE {where} ORDER BY embedding <=> %s::vector,id LIMIT 80",
                (v, *params, v),
            ).fetchall()
        scores, facts = {}, {}
        for ranking in (keyword, semantic):
            for rank, row in enumerate(ranking, 1):
                facts[row["id"]] = row["facts"]
                scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
        for row in exact:
            facts[row["id"]] = row["facts"]
            scores[row["id"]] = 1.0
        results = []
        for pid in sorted(scores, key=lambda x: (-scores[x], x)):
            p = facts[pid]
            if requirement_reasons(p, request.requirements):
                continue
            results.append(
                {
                    k: p[k]
                    for k in (
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
                }
                | {"score": scores[pid], "match_is_suitability_proof": False}
            )
            if len(results) == request.limit:
                break
        return {
            "products": results,
            "generation": str(active["id"]),
            "model": active["model_key"],
            "strategy": strategy,
            "note": "Discovery candidates only. Inspect requirements and current price/availability before purchase.",
        }
