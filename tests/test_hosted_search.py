from copy import deepcopy
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from aimo import search_provider as provider
from aimo.api import app
from aimo.catalog import rich_search_text
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import activate_catalog, publish
from aimo.schemas import Requirements, SearchRequest, SearchResponse
from aimo.search import search_products


def response_vector(index=0, value=1):
    return {"index": index, "embedding": [value] + [0] * (provider.DIMENSIONS - 1)}


def test_embeddings_reorder_and_format_query(monkeypatch):
    calls = []

    def post(endpoint, payload):
        calls.append((endpoint, payload))
        return {
            "model": "Qwen/Qwen3-Embedding-8B",
            "data": [response_vector(1, 2), response_vector(0)],
        }

    monkeypatch.setattr(provider, "post", post)
    assert provider.embeddings(["milk", "salad"])[1][0] == 1
    assert calls[0][1]["input"] == ["milk", "salad"]
    provider.embeddings(["milk", "salad"], query=True)
    assert calls[1][1]["input"][0].startswith("Instruct: ")
    assert calls[1][1]["input"][0].endswith("Query: milk")


@pytest.mark.parametrize(
    "corruption", ["model", "missing", "duplicate", "dimensions", "nan", "zero", "index"]
)
def test_invalid_embeddings_are_rejected(monkeypatch, corruption):
    body = {"model": provider.EMBEDDING_MODEL, "data": [response_vector(0), response_vector(1)]}
    if corruption == "model":
        body["model"] = "different-model"
    elif corruption == "missing":
        body["data"].pop()
    elif corruption == "duplicate":
        body["data"][1]["index"] = 0
    elif corruption == "dimensions":
        body["data"][0]["embedding"].pop()
    elif corruption == "nan":
        body["data"][0]["embedding"][0] = float("nan")
    elif corruption == "zero":
        body["data"][0]["embedding"][0] = 0
    else:
        body["data"][0]["index"] = -1
    monkeypatch.setattr(provider, "post", lambda *args: body)
    with pytest.raises(Problem, match="invalid response"):
        provider.embeddings(["milk", "salad"])


@pytest.mark.parametrize("status,attempts", [(401, 1), (402, 1), (429, 2), (503, 2), (302, 1)])
def test_provider_retries_are_bounded_and_errors_redacted(monkeypatch, status, attempts):
    calls = []
    original_client = httpx.Client
    monkeypatch.setattr(settings(), "search_api_key", "private-test-key")
    monkeypatch.setattr(provider.time, "sleep", lambda _: None)

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "private-test-key and supplier data"})

    monkeypatch.setattr(
        provider.httpx,
        "Client",
        lambda **kw: original_client(**kw, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(Problem) as error:
        provider.post("embeddings", {"input": ["milk"]})
    assert len(calls) == attempts
    assert "private-test-key" not in str(error.value)
    assert calls[0].url == "https://openrouter.ai/api/v1/embeddings"


@pytest.mark.parametrize(
    "rows",
    [
        [{"index": 0, "relevance_score": 1}, {"index": 0, "relevance_score": 0}],
        [{"index": 99, "relevance_score": 1}, {"index": 1, "relevance_score": 0}],
        [{"index": 0, "relevance_score": float("nan")}, {"index": 1, "relevance_score": 0}],
        [{"index": 0, "relevance_score": 1}],
    ],
)
def test_reranker_cannot_inject_candidates(monkeypatch, rows):
    monkeypatch.setattr(provider, "post", lambda *args: {"results": rows})
    with pytest.raises(Problem):
        provider.rerank("milk", ["milk", "salad"])


def test_reranker_uses_8b_and_ignores_provider_document_text(monkeypatch):
    def post(endpoint, payload):
        assert endpoint == "rerank"
        assert payload == {
            "model": "qwen/qwen3-reranker-8b",
            "query": "milk",
            "documents": ["milk", "salad"],
            "top_n": 2,
            "return_documents": False,
        }
        return {
            "results": [
                {"index": 1, "relevance_score": 0.1, "document": {"text": "fabricated"}},
                {"index": 0, "relevance_score": 0.9, "document": {"text": "fabricated"}},
            ]
        }

    monkeypatch.setattr(provider, "post", post)
    assert provider.rerank("milk", ["milk", "salad"]) == [(0, 0.9), (1, 0.1)]


def test_rich_text_is_bounded_and_preserves_source_facts():
    facts = fixture_facts()[0]
    original = deepcopy(facts)
    facts["brand"] = "Real brand"
    facts["descriptions"] = [{"language": "fi", "value": "real description " * 1000}]
    text = rich_search_text(facts)
    assert len(text) <= 8000 and "Real brand" in text
    assert facts["claims"] == original["claims"]


@pytest.fixture
def hosted_catalog(monkeypatch):
    cfg = settings()
    data = fixture_facts()
    before = publish(data, "before-hosted", fingerprint(data))
    monkeypatch.setattr(cfg, "embedding_backend", "openrouter")
    monkeypatch.setattr(cfg, "search_api_key", "test-only")
    monkeypatch.setattr(
        provider,
        "embeddings",
        lambda texts, query=False: [response_vector()["embedding"] for _ in texts],
    )
    try:
        yield data, before
    finally:
        monkeypatch.setattr(cfg, "embedding_backend", "fixture")
        publish(fixture_facts(), "restore-fixtures", fingerprint(fixture_facts()))


def test_staging_cutover_rollback_and_dimensions(hosted_catalog, agent):
    data, before = hosted_catalog
    staged = publish(data, "hosted-staged", fingerprint(data), activate=False)
    publish(data, "newer-unselected-stage", fingerprint(data), activate=False)
    assert staged["active"] is False
    with connection() as c:
        assert (
            str(c.execute("SELECT generation FROM active_catalog").fetchone()["generation"])
            == before["generation"]
        )
    with pytest.raises(Problem) as error:
        search_products(agent, SearchRequest(query="milk"))
    assert error.value.code == "MODEL_MISMATCH"
    activate_catalog(staged["generation"])
    publish(data, "another-unselected-stage", fingerprint(data), activate=False)
    activate_catalog(staged["generation"])  # Idempotent, including rollback retention.
    with connection() as c:
        assert c.execute(
            "SELECT count(*) AS n FROM products WHERE generation=%s AND vector_dims(embedding)=4096",
            (staged["generation"],),
        ).fetchone()["n"] == len(data)
    # Database itself rejects a vector from the wrong model dimension.
    with pytest.raises(psycopg.errors.RaiseException):
        with connection() as c:
            c.execute(
                "UPDATE products SET embedding='[1,0]'::vector WHERE generation=%s",
                (staged["generation"],),
            )
    settings().embedding_backend = "fixture"
    activate_catalog(before["generation"])
    assert search_products(agent, SearchRequest(query="464306"))["products"][0]["id"] == "464306"


def test_paid_import_resumes_completed_batches(hosted_catalog, monkeypatch):
    data, before = hosted_catalog
    suffix = str(uuid4())
    for p in data:
        p["names"]["en"] += suffix
    monkeypatch.setattr(settings(), "embedding_batch_size", 2)
    monkeypatch.setattr(settings(), "embedding_workers", 1)
    calls = []

    def flaky(texts, query=False):
        calls.extend(texts)
        if len(calls) > 2:
            raise Problem("SEARCH_PROVIDER_UNAVAILABLE", "test failure", 503)
        return [response_vector()["embedding"] for _ in texts]

    monkeypatch.setattr(provider, "embeddings", flaky)
    with pytest.raises(Problem):
        publish(data, "interrupted", fingerprint(data))
    with connection() as c:
        assert (
            str(c.execute("SELECT generation FROM active_catalog").fetchone()["generation"])
            == before["generation"]
        )
    monkeypatch.setattr(
        provider,
        "embeddings",
        lambda texts, query=False: [response_vector()["embedding"] for _ in texts],
    )
    result = publish(data, "resumed", fingerprint(data), activate=False)
    assert result["reused_embeddings"] == 2
    assert result["new_embeddings"] == len(data) - 2


def test_exact_ids_readiness_and_filters_do_not_depend_on_provider(
    hosted_catalog, monkeypatch, agent
):
    data, _ = hosted_catalog
    publish(data, "hosted", fingerprint(data))
    monkeypatch.setattr(
        provider, "embeddings", lambda *a, **kw: pytest.fail("Unexpected embedding call")
    )
    monkeypatch.setattr(provider, "rerank", lambda *a, **kw: pytest.fail("Unexpected rerank call"))
    assert search_products(agent, SearchRequest(query="464306"))["products"][0]["id"] == "464306"
    assert (
        search_products(
            agent, SearchRequest(query="464306", requirements=Requirements(milk_free=True))
        )["products"]
        == []
    )
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        monkeypatch.setattr(settings(), "search_api_key", "")
        assert client.get("/health/ready").status_code == 503


def test_rerank_filters_before_provider_and_reports_outage(hosted_catalog, monkeypatch, agent):
    data, _ = hosted_catalog
    publish(data, "hosted", fingerprint(data))
    documents = []

    def rank(query, docs):
        documents.extend(docs)
        return [(i, float(i)) for i in reversed(range(len(docs)))]

    monkeypatch.setattr(provider, "rerank", rank)
    request = SearchRequest(query="milk", requirements=Requirements(lactose_free=True), limit=20)
    result = search_products(agent, request)
    SearchResponse.model_validate(result)
    assert result["rerank_status"] == "applied"
    assert documents and len(documents) <= 30
    assert not any("468044" in d or "469429" in d for d in documents)
    assert all("FREE_FROM_LACTOSE" in p["claims"] for p in result["products"])

    def unavailable(*args):
        raise Problem("SEARCH_PROVIDER_UNAVAILABLE", "test outage", 503)

    monkeypatch.setattr(provider, "rerank", unavailable)
    fallback = search_products(agent, request)
    assert fallback["rerank_status"] == "unavailable" and fallback["products"]
    assert all("FREE_FROM_LACTOSE" in p["claims"] for p in fallback["products"])


def test_credentials_required_before_network(monkeypatch):
    monkeypatch.setattr(settings(), "search_api_key", "")
    monkeypatch.setattr(provider.httpx, "Client", lambda **kw: pytest.fail("Unexpected network"))
    with pytest.raises(Problem) as error:
        provider.embeddings(["milk"])
    assert error.value.code == "SEARCH_NOT_CONFIGURED"


def test_migration_preserves_existing_384_dimension_rows():
    from aimo.cli import ROOT

    name = "upgrade_" + uuid4().hex
    with connection() as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        try:
            c.execute(sql.SQL("SET LOCAL search_path TO {},public").format(sql.Identifier(name)))
            c.execute((ROOT / "migrations/001_initial.sql").read_text())
            generation = uuid4()
            old_vector = "[1," + ",".join("0" for _ in range(383)) + "]"
            c.execute(
                "INSERT INTO catalog_generations(id,source,source_hash,model_key,product_count) VALUES(%s,'old','hash','legacy-e5',1)",
                (generation,),
            )
            c.execute(
                "INSERT INTO products(generation,id,search_text,facts,embedding) VALUES(%s,'p','milk','{}',%s::vector)",
                (generation, old_vector),
            )
            c.execute(
                "INSERT INTO embedding_cache VALUES('legacy-e5','hash',%s::vector)", (old_vector,)
            )
            c.execute("INSERT INTO active_catalog VALUES(true,%s)", (generation,))
            c.execute((ROOT / "migrations/004_hosted_search.sql").read_text())
            assert (
                c.execute("SELECT embedding_dimensions FROM catalog_generations").fetchone()[
                    "embedding_dimensions"
                ]
                == 384
            )
            assert (
                c.execute("SELECT vector_dims(embedding) AS n FROM products").fetchone()["n"] == 384
            )
            assert (
                c.execute("SELECT vector_dims(embedding) AS n FROM embedding_cache").fetchone()["n"]
                == 384
            )
            assert (
                c.execute("SELECT generation FROM active_catalog").fetchone()["generation"]
                == generation
            )
        finally:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
