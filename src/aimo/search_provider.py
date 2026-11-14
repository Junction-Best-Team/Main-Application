"""Bounded OpenRouter search calls. Never log credentials, source text or provider bodies."""

import math
import time

import httpx

from aimo.config import settings
from aimo.db import Problem

EMBEDDING_MODEL = "qwen/qwen3-embedding-8b"
RERANK_MODEL = "qwen/qwen3-reranker-0.6b"
DIMENSIONS = 4096
QUERY_INSTRUCTION = "Given a food purchasing request, retrieve matching wholesale food products."
# Bump when document construction or query instructions change.
PROFILE = "catalog-v2-query-v1"


def require_credentials():
    if not settings().search_api_key:
        raise Problem("SEARCH_NOT_CONFIGURED", "Configure SEARCH_API_KEY for hosted search.", 503)


def post(endpoint, payload):
    require_credentials()
    cfg = settings()
    with httpx.Client(
        base_url="https://openrouter.ai/api/v1/",
        headers={"Authorization": f"Bearer {cfg.search_api_key}"},
        timeout=cfg.search_timeout_seconds,
        follow_redirects=False,
    ) as client:
        for attempt in range(cfg.search_max_attempts):
            retryable = False
            try:
                response = client.post(endpoint, json=payload)
                if response.status_code == 200:
                    body = response.json()
                    if isinstance(body, dict) and "error" not in body:
                        return body
                    break
                retryable = response.status_code in (408, 429, 500, 502, 503, 504)
            except (httpx.TimeoutException, httpx.TransportError):
                retryable = True
            except ValueError:
                break
            if not retryable or attempt + 1 == cfg.search_max_attempts:
                break
            time.sleep(0.25 * (attempt + 1))
    raise Problem(
        "SEARCH_PROVIDER_UNAVAILABLE", "Search provider is unavailable; retry later.", 503
    )


def invalid_response():
    return Problem("SEARCH_PROVIDER_INVALID", "Search provider returned an invalid response.", 502)


def embeddings(texts, query=False):
    if not texts:
        return []
    if len(texts) > 128 or any(not t or len(t) > 12000 for t in texts):
        raise ValueError("Embedding request exceeds the bounded text batch")
    inputs = [f"Instruct: {QUERY_INSTRUCTION}\nQuery: {t}" for t in texts] if query else texts
    body = post(
        "embeddings",
        {
            "model": EMBEDDING_MODEL,
            "input": inputs,
            "encoding_format": "float",
        },
    )
    try:
        # OpenRouter may echo either its slug or the upstream Hugging Face ID.
        if body.get("model") not in (EMBEDDING_MODEL, "Qwen/Qwen3-Embedding-8B"):
            raise ValueError("Unexpected embedding model")
        data = body["data"]
        if len(data) != len(texts):
            raise ValueError("Incomplete embedding batch")
        result = [None] * len(texts)
        for item in data:
            index, values = item["index"], item["embedding"]
            if type(index) is not int or not 0 <= index < len(texts) or result[index] is not None:
                raise ValueError("Invalid embedding index")
            if not isinstance(values, list) or len(values) != DIMENSIONS:
                raise ValueError("Invalid dimensions")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError("Invalid vector")
            norm = math.sqrt(sum(v * v for v in values))
            if not math.isfinite(norm) or norm == 0:
                raise ValueError("Invalid vector norm")
            result[index] = [v / norm for v in values]
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        raise invalid_response() from None


def rerank(query, documents):
    """Return only validated positions into our own already-filtered candidate list."""
    if not documents:
        return []
    if len(documents) > settings().rerank_candidates:
        raise ValueError("Too many reranking candidates")
    body = post(
        "rerank",
        {
            "model": RERANK_MODEL,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        },
    )
    try:
        rows = body["results"]
        if len(rows) != len(documents):
            raise ValueError("Incomplete rerank")
        seen, ranked = set(), []
        for row in rows:
            index, score = row["index"], row["relevance_score"]
            if type(index) is not int or not 0 <= index < len(documents) or index in seen:
                raise ValueError("Invalid candidate index")
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("Invalid score")
            seen.add(index)
            ranked.append((index, score))
        return sorted(ranked, key=lambda item: (-item[1], item[0]))
    except (KeyError, TypeError, ValueError):
        raise invalid_response() from None
