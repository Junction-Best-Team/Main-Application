"""Independent recipe search profile; reuse the configured embedding provider."""

import math

from aimo import search
from aimo.config import settings
from aimo.db import Problem

PROFILE = "recipes-v1"
INSTRUCTION = "Given a meal request, retrieve relevant cooking recipes and meal ideas."


def hosted():
    return settings().embedding_backend == "openrouter"


def model_key():
    return search.model_key() + ":" + PROFILE


def embeddings(texts, query=False):
    if hosted():
        from aimo.search_provider import embeddings as provider_embeddings

        # Product provider query=True injects a product-specific instruction.
        texts = [f"Instruct: {INSTRUCTION}\nQuery: {t}" for t in texts] if query else texts
        values = provider_embeddings(texts, query=False)
    else:
        values = search.embed(texts, query=query)
    dim = search.dimensions()
    if len(values) != len(texts) or any(
        len(v) != dim or any(not math.isfinite(n) for n in v) or not any(v) for v in values
    ):
        raise Problem("RECIPE_EMBEDDING_INVALID", "Recipe embedding response is invalid.", 502)
    return values


def text(recipe):
    return " ".join(
        [
            recipe.title,
            recipe.summary,
            recipe.category,
            *[i.name + " " + i.form for i in recipe.ingredients],
            *recipe.instructions,
        ]
    )[:12000]
