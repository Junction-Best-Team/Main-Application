"""Explicit complete-snapshot import. Atomic publication and persistent embedding reuse."""

import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx

from aimo.catalog import normalize, search_text
from aimo.config import settings
from aimo.db import connection, fingerprint, js
from aimo.search import embed, model_key, vector

CATALOG_SHA256 = "50651aae31ca842112afdc16fcce92f9858d7f5d05e9928a3748aef16b22ea02"


def download(path: Path):
    cfg = settings()
    if not cfg.valio_aimo_api_key:
        raise ValueError("VALIO_AIMO_API_KEY is required for download")
    # Never forward API credentials to a redirect destination.
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        response = client.get(
            cfg.valio_aimo_base_url + "/api/products/download",
            headers={"X-API-Key": cfg.valio_aimo_api_key},
        )
        if response.is_redirect:
            url = httpx.URL(cfg.valio_aimo_base_url).join(response.headers["location"])
            if url.scheme != "https":
                raise ValueError("Catalog redirect must use HTTPS")
            response = client.get(url, follow_redirects=True)
        response.raise_for_status()
        path.write_bytes(response.content)


def ingest_file(path: Path, expected_count=17546, expected_sha=CATALOG_SHA256):
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_sha:
        raise ValueError("Snapshot hash differs; explicitly verify and supply its expected SHA-256")
    records = json.loads(content, parse_float=Decimal)
    if not isinstance(records, list) or len(records) != expected_count:
        raise ValueError("Snapshot count differs; incomplete imports are not published")
    if len({p["id"] for p in records}) != len(records):
        raise ValueError("Duplicate product identifiers")
    source = f"{path.name}; sha256:{actual}"
    facts = [normalize(p, source) for p in records if not p.get("deleted", False)]
    return publish(facts, source, actual)


def publish(facts, source, source_hash):
    if not facts or len({p["id"] for p in facts}) != len(facts):
        raise ValueError("Empty or duplicate import")
    key = model_key()
    text_by_hash = {fingerprint(search_text(p)): search_text(p) for p in facts}
    with connection() as c:
        existing = {
            r["text_hash"]: r["embedding"]
            for r in c.execute(
                "SELECT text_hash,embedding::text FROM embedding_cache WHERE model_key=%s", (key,)
            ).fetchall()
        }
    missing = [(h, t) for h, t in text_by_hash.items() if h not in existing]
    generated = {}
    for start in range(0, len(missing), 128):
        batch = missing[start : start + 128]
        values = embed([t for _, t in batch])
        if len(values) != len(batch) or any(len(v) != 384 for v in values):
            raise ValueError("Embedding shape is incompatible with the catalog schema")
        generated.update({h: vector(v) for (h, _), v in zip(batch, values, strict=True)})
        print(f"Embedded {min(start + 128, len(missing))}/{len(missing)} changed texts", flush=True)
    all_vectors = existing | generated
    generation = uuid4()
    with connection() as c:
        # One publisher at a time. Errors roll back the generation and pointer together.
        c.execute("SELECT pg_advisory_xact_lock(893017)")
        c.execute(
            "INSERT INTO catalog_generations(id,source,source_hash,model_key,product_count) VALUES(%s,%s,%s,%s,%s)",
            (generation, source, source_hash, key, len(facts)),
        )
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO embedding_cache VALUES(%s,%s,%s::vector) ON CONFLICT DO NOTHING",
                [(key, h, v) for h, v in generated.items()],
            )
            cur.executemany(
                "INSERT INTO products(generation,id,gtin,search_text,facts,embedding) VALUES(%s,%s,%s,%s,%s,%s::vector)",
                [
                    (
                        generation,
                        p["id"],
                        p.get("gtin"),
                        search_text(p),
                        js(p),
                        all_vectors[fingerprint(search_text(p))],
                    )
                    for p in facts
                ],
            )
        c.execute(
            "INSERT INTO active_catalog(singleton,generation) VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET generation=excluded.generation",
            (generation,),
        )
    return {
        "generation": str(generation),
        "products": len(facts),
        "new_embeddings": len(generated),
        "reused_embeddings": len(text_by_hash) - len(generated),
        "volume_evidence": dict(Counter(p["measures"]["L"]["status"] for p in facts)),
        "allergen_conflicts": sum(bool(p["allergen_conflicts"]) for p in facts),
        "model": key,
        "source_hash": source_hash,
    }
