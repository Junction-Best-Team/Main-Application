"""Real PostgreSQL cutover with authored Google vectors, never a paid import."""

import pytest

from aimo import google_search, recipe_search, search
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import activate_catalog, publish
from aimo.recipe_schemas import RecipeSearch
from aimo.recipes import search_recipes
from aimo.schemas import SearchRequest
from aimo.worker import check_readiness


def test_google_product_and_recipe_indexes_rebuild_without_mixing_old_vectors(
    monkeypatch, agent, tmp_path
):
    from test_recipes import import_fixture

    cfg = settings()
    with connection() as c:
        # A recipe reset cascades into guarded history (PER-002): say it is deliberate.
        c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        c.execute("TRUNCATE recipes,recipe_catalogs,recipe_embedding_cache CASCADE")
    import_fixture(tmp_path)
    data = fixture_facts()
    previous = publish(data, "before-google", fingerprint(data))
    cfg_values = {
        "embedding_backend": "google",
        "gemini_api_key": "synthetic-google",
        "llm_provider": "google",
        "llm_api_key": "",
        "rerank_enabled": True,
    }
    for key, value in cfg_values.items():
        monkeypatch.setattr(cfg, key, value)
    calls = []

    def embed(texts, query=False):
        calls.append((list(texts), query))
        return [[1.0] + [0.0] * 767 for _ in texts]

    monkeypatch.setattr(google_search, "embeddings", embed)
    monkeypatch.setattr(
        google_search, "rerank", lambda query, docs: [(i, 1 / (i + 1)) for i in range(len(docs))]
    )
    try:
        with pytest.raises(Problem) as error:
            search.search_products(agent, SearchRequest(query="milk"))
        assert error.value.code == "MODEL_MISMATCH"
        with pytest.raises(Problem) as error:
            search_recipes(agent, RecipeSearch(query="pasta"))
        assert error.value.code == "RECIPE_MODEL_MISMATCH"
        staged = publish(data, "google-staged", fingerprint(data), activate=False)
        with connection() as c:
            assert (
                str(c.execute("SELECT generation FROM active_catalog").fetchone()["generation"])
                == previous["generation"]
            )
        activate_catalog(staged["generation"])
        check_readiness()  # Google key alone is enough; no OpenRouter credential.
        result = search.search_products(agent, SearchRequest(query="milk"))
        assert result["products"] and result["rerank_status"] == "applied"
        assert result["model"] == search.model_key()
        with connection() as c:
            assert c.execute(
                "SELECT count(*) AS n FROM products WHERE generation=%s AND vector_dims(embedding)=768",
                (staged["generation"],),
            ).fetchone()["n"] == len(data)
        rebuilt = import_fixture(tmp_path)[3]
        assert rebuilt["embedded"] > 0
        assert search_recipes(agent, RecipeSearch(query="pasta"))["recipes"]
        assert recipe_search.model_key().startswith("google:gemini-embedding-2:768:")
        before = len(calls)
        assert import_fixture(tmp_path)[3]["embedded"] == 0
        assert len(calls) == before  # Completed Google embeddings are reused.
    finally:
        monkeypatch.setattr(cfg, "embedding_backend", "fixture")
        publish(data, "restore-fixtures", fingerprint(data))
        with connection() as c:
            c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
            c.execute("TRUNCATE recipes,recipe_catalogs,recipe_embedding_cache CASCADE")
