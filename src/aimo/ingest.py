"""Explicit complete-snapshot import. Atomic publication and persistent embedding reuse."""

import hashlib
import json
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx

from aimo.catalog import normalize
from aimo.config import settings
from aimo.db import connection, fingerprint, js, now
from aimo.search import dimensions, document_text, embed, model_key, vector

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


def ingest_file(
    path: Path,
    expected_count=17546,
    expected_sha=CATALOG_SHA256,
    *,
    activate=True,
    carry_withdrawn=True,
):
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_sha:
        raise ValueError("Snapshot hash differs; explicitly verify and supply its expected SHA-256")
    records = json.loads(content, parse_float=Decimal)
    if not isinstance(records, list) or len(records) != expected_count:
        raise ValueError("Snapshot count differs; incomplete imports are not published")
    for index, record in enumerate(records):
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("id"), str)
            or not record["id"]
        ):
            raise ValueError(
                f"Malformed catalog record #{index}: expected an object with a non-empty string id"
            )
    if len({p["id"] for p in records}) != len(records):
        raise ValueError("Duplicate product identifiers")
    source = f"{path.name}; sha256:{actual}"
    # Retain withdrawal facts for exact lookup/denial; discovery filters them out.
    facts = [_normalize_record(index, p, source) for index, p in enumerate(records)]
    if carry_withdrawn:  # DIS-008; tests of unrelated snapshot rules opt out
        facts += _absent_as_withdrawn(facts)
    return publish(facts, source, actual, activate=activate)


def _absent_as_withdrawn(facts):
    """Products of the active catalog missing from a newer snapshot stay as withdrawn (DIS-008).

    The earlier facts are kept unchanged except `deleted`, so exact lookup still returns the product
    and every purchase check denies it as withdrawn. Their withdrawal date is carried by `publish`.
    """
    new_ids = [p["id"] for p in facts]
    with connection() as c:
        rows = c.execute(
            "SELECT p.facts FROM products p JOIN active_catalog a ON a.generation=p.generation "
            "WHERE NOT (p.id = ANY(%s))",
            (new_ids,),
        ).fetchall()
    return [dict(r["facts"], deleted=True) for r in rows]


def _normalize_record(index, raw, source):
    """Normalize one supplier record; any structural defect names the record, never a bare KeyError."""
    where = f"Malformed catalog record #{index} (id {raw['id']})"
    try:
        facts = normalize(raw, source)
        step = Decimal(facts["order_step"])
        if not all(Decimal(size).is_finite() for size in facts["units"].values()):
            raise ValueError("non-finite unit size")
    except KeyError as error:
        raise ValueError(f"{where}: missing field {error.args[0]!r}") from None
    except (TypeError, AttributeError, ArithmeticError, ValueError) as error:
        raise ValueError(
            f"{where}: unexpected value or structure ({type(error).__name__})"
        ) from None
    if not step.is_finite() or step < 0:
        raise ValueError(f"{where}: allowedLotSize must be a finite number of at least 0")
    return facts


def publish(facts, source, source_hash, *, activate=True):
    if not facts or len({p["id"] for p in facts}) != len(facts):
        raise ValueError("Empty or duplicate import")
    key = model_key()
    text_by_hash = {fingerprint(document_text(p)): document_text(p) for p in facts}
    with connection() as c:
        existing = {
            r["text_hash"]
            for r in c.execute(
                "SELECT text_hash FROM embedding_cache WHERE model_key=%s AND vector_dims(embedding)=%s",
                (key, dimensions()),
            ).fetchall()
        }
    missing = [(h, t) for h, t in text_by_hash.items() if h not in existing]
    batch_size = settings().embedding_batch_size

    def cache_batch(batch):
        values = embed([t for _, t in batch])
        if len(values) != len(batch) or any(len(v) != dimensions() for v in values):
            raise ValueError("Embedding shape is incompatible with the catalog schema")
        # Commit reusable batches independently. An interrupted paid import resumes
        # without re-buying completed embeddings; no partial catalog is exposed.
        with connection() as c:
            with c.cursor() as cur:
                cur.executemany(
                    "INSERT INTO embedding_cache(model_key,text_hash,embedding) VALUES(%s,%s,%s::vector) "
                    "ON CONFLICT(model_key,text_hash) DO UPDATE SET embedding=excluded.embedding",
                    [(key, h, vector(v)) for (h, _), v in zip(batch, values, strict=True)],
                )
        return len(batch)

    batches = iter(
        missing[start : start + batch_size] for start in range(0, len(missing), batch_size)
    )
    workers = settings().embedding_workers if settings().embedding_backend == "openrouter" else 1
    generated = 0
    # Keep at most four batches in flight; don't queue the whole paid import.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {executor.submit(cache_batch, batch) for _, batch in zip(range(workers), batches)}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            try:
                generated += sum(future.result() for future in done)
            except Exception:
                for future in pending:
                    future.cancel()
                raise
            print(f"Embedded {generated}/{len(missing)} changed texts", flush=True)
            for _ in done:
                batch = next(batches, None)
                if batch:
                    pending.add(executor.submit(cache_batch, batch))
    generation = uuid4()
    with connection() as c:
        # One publisher at a time. Errors roll back the generation and pointer together.
        c.execute("SELECT pg_advisory_xact_lock(893017)")
        c.execute(
            "INSERT INTO catalog_generations(id,source,source_hash,model_key,product_count,embedding_dimensions) VALUES(%s,%s,%s,%s,%s,%s)",
            (generation, source, source_hash, key, len(facts), dimensions()),
        )
        # The first date a product was withdrawn wins; a product that returns clears it.
        prior = {
            r["id"]: r["withdrawn_since"]
            for r in c.execute(
                "SELECT p.id, p.withdrawn_since FROM products p JOIN active_catalog a "
                "ON a.generation=p.generation WHERE p.withdrawn_since IS NOT NULL"
            )
        }
        stamp = now()
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO products(generation,id,gtin,search_text,facts,embedding,withdrawn_since) "
                "SELECT %s,%s,%s,%s,%s,embedding,%s FROM embedding_cache WHERE model_key=%s AND text_hash=%s",
                [
                    (
                        generation,
                        p["id"],
                        p.get("gtin"),
                        document_text(p),
                        js(p),
                        (prior.get(p["id"]) or stamp) if p["deleted"] else None,
                        key,
                        fingerprint(document_text(p)),
                    )
                    for p in facts
                ],
            )
            if cur.rowcount != len(facts):
                raise ValueError("Incomplete product import")
        if activate:
            _activate(c, generation)
    return {
        "generation": str(generation),
        "products": len(facts),
        "withdrawn_products": sum(bool(p["deleted"]) for p in facts),
        "new_embeddings": generated,
        "reused_embeddings": len(text_by_hash) - generated,
        "active": activate,
        "volume_evidence": dict(Counter(p["measures"]["L"]["status"] for p in facts)),
        "allergen_conflicts": sum(bool(p["allergen_conflicts"]) for p in facts),
        "model": key,
        "source_hash": source_hash,
    }


def _activate(c, generation):
    previous = c.execute("SELECT generation FROM active_catalog").fetchone()
    previous_id = previous["generation"] if previous else None
    if str(previous_id) == str(generation):
        return  # An activation retry must not prune the retained rollback catalog.
    c.execute(
        "INSERT INTO active_catalog(singleton,generation) VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET generation=excluded.generation",
        (generation,),
    )
    # Retain rollback generations that differ from the new one. A rerun of an identical snapshot
    # (same source hash and embedding model) must not consume the only different rollback target.
    c.execute(
        """DELETE FROM products WHERE generation <> %s AND generation NOT IN (
        SELECT id FROM catalog_generations WHERE id <> %s
        AND NOT (source_hash=(SELECT source_hash FROM catalog_generations WHERE id=%s)
                 AND model_key=(SELECT model_key FROM catalog_generations WHERE id=%s))
        ORDER BY (id=%s) DESC NULLS LAST,created_at DESC,id DESC LIMIT %s)""",
        (
            generation,
            generation,
            generation,
            generation,
            previous_id,
            settings().catalog_generations_to_keep - 1,
        ),
    )


def activate_catalog(generation):
    """Explicit cutover or rollback using the target serving configuration."""
    with connection() as c:
        c.execute("SELECT pg_advisory_xact_lock(893017)")
        row = c.execute("SELECT * FROM catalog_generations WHERE id=%s", (generation,)).fetchone()
        if (
            not row
            or row["model_key"] != model_key()
            or row["embedding_dimensions"] != dimensions()
        ):
            raise ValueError("Target catalog does not match the configured embedding profile")
        actual = c.execute(
            "SELECT count(*) AS n FROM products WHERE generation=%s AND vector_dims(embedding)=%s",
            (generation, dimensions()),
        ).fetchone()["n"]
        if actual == 0 or actual != row["product_count"]:
            raise ValueError("Target catalog is incomplete or has been pruned; reimport it")
        _activate(c, generation)
    return {"generation": str(generation), "products": actual, "model": model_key()}
