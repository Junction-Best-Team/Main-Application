"""Complete-snapshot catalog import: strict validation, atomic publication, persistent
embedding reuse, and the unattended `aimo sync-catalog` run used by the Kubernetes CronJob.

Never log credentials, signed download URLs or snapshot contents. Errors carry a stable
code and a fixed message so a Job's logs are safe to share.
"""

import asyncio
import hashlib
import inspect
import json
import os
import tempfile
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg

from aimo.catalog import MASS, VOLUME, normalize, rich_search_text, search_text
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, js, now
from aimo.search import dimensions, document_text, embed, model_key, vector

# The approved static challenge snapshot. Changing either value is an explicit approval of
# different supplier data; a hash computed from the downloaded bytes never replaces it.
CATALOG_SHA256 = "50651aae31ca842112afdc16fcce92f9858d7f5d05e9928a3748aef16b22ea02"
CATALOG_PRODUCT_COUNT = 17546
# Stable provenance name, so unchanged data yields identical product facts across imports.
SNAPSHOT_NAME = "valio_aimo_junction26_product_data.json"
DOWNLOAD_PATH = "/api/products/download"
# Bump when stored catalog semantics change in a way the source digest below cannot see.
IMPORT_PROFILE_VERSION = 2
# Transaction lock: one publisher/activation at a time (unchanged since the first import).
PUBLISH_LOCK_KEY = 893017
# Session lock: one ingestion run (scheduled, manual Job or `aimo ingest`) at a time.
INGESTION_LOCK_KEY = 893019
MAX_REDIRECTS = 3
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_sleep = time.sleep


class CatalogError(ValueError):
    """An import failure with a stable, log-safe code. The active catalog is never changed."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class IngestionRunning(CatalogError):
    def __init__(self):
        super().__init__("INGESTION_RUNNING", "Another catalog ingestion run holds the lock")


class _Retryable(Exception):
    pass


# --- profile ---------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def import_profile() -> str:
    """Identity of the code that turns supplier records into stored facts and search documents.

    Any edit to normalization or document construction changes the digest, so an unattended
    sync can never treat a catalog built by different import code as current.
    """
    parts = [
        inspect.getsource(f) for f in (normalize, search_text, rich_search_text, document_text)
    ]
    parts += [repr(sorted(VOLUME.items())), repr(sorted(MASS.items()))]
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return f"catalog-import-v{IMPORT_PROFILE_VERSION}:{digest}"


# --- coordination ----------------------------------------------------------------------------


class IngestionLock:
    """A session-level advisory lock on a dedicated autocommit connection.

    The session holds no transaction while downloading or embedding. Publication re-checks
    that this backend still holds the lock, so a dropped connection cannot let two runs publish.
    """

    def __init__(self, conn, pid):
        self.conn, self.pid = conn, pid

    def verify(self, c):
        held = c.execute(
            "SELECT 1 FROM pg_locks WHERE locktype='advisory' AND classid=0 AND objid=%s "
            "AND objsubid=1 AND pid=%s AND granted",
            (INGESTION_LOCK_KEY, self.pid),
        ).fetchone()
        if not held:
            raise CatalogError("LOCK_LOST", "The ingestion lock was lost; nothing was published")


@contextmanager
def ingestion_lock():
    try:
        conn = psycopg.connect(
            settings().database_url,
            autocommit=True,
            connect_timeout=5,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
            application_name="aimo-catalog-ingestion",
        )
    except psycopg.OperationalError:
        raise CatalogError(
            "DATABASE_UNAVAILABLE", "Cannot connect to the catalog database"
        ) from None
    with conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (INGESTION_LOCK_KEY,)).fetchone()[0]:
            raise IngestionRunning()
        pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
        try:
            yield IngestionLock(conn, pid)
        finally:
            try:
                conn.execute("SELECT pg_advisory_unlock(%s)", (INGESTION_LOCK_KEY,))
            except psycopg.Error:
                pass  # Closing the session releases the lock anyway.


# --- download --------------------------------------------------------------------------------


def download(path: Path) -> str:
    """Stream the supplier snapshot to `path` with bounded time, size and retries.

    Returns the SHA-256 of the written bytes. Callers compare it with an independently
    approved value; it is never itself evidence that the bytes are correct.
    """
    cfg = settings()
    if not cfg.valio_aimo_api_key:
        raise CatalogError("CREDENTIALS_MISSING", "VALIO_AIMO_API_KEY is required for download")
    if not cfg.valio_aimo_base_url.startswith("https://"):
        raise CatalogError("DOWNLOAD_REJECTED", "The supplier base URL must use HTTPS")
    for attempt in range(1, cfg.catalog_download_attempts + 1):
        try:
            return asyncio.run(_download_once(path, cfg))
        except (_Retryable, TimeoutError, httpx.TransportError):
            if attempt == cfg.catalog_download_attempts:
                raise CatalogError(
                    "DOWNLOAD_FAILED", "Catalog download failed after bounded retries"
                ) from None
            _sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")  # pragma: no cover


async def _download_once(path, cfg):
    url = httpx.URL(cfg.valio_aimo_base_url + DOWNLOAD_PATH)
    headers = {"X-API-Key": cfg.valio_aimo_api_key}
    # Cancel the actual network operation at the deadline, including incomplete
    # response headers. HTTPX's idle read timeout alone resets on each read.
    deadline = time.monotonic() + cfg.catalog_download_deadline_seconds
    async with (
        asyncio.timeout(cfg.catalog_download_deadline_seconds),
        httpx.AsyncClient(follow_redirects=False) as client,
    ):
        for _ in range(MAX_REDIRECTS + 1):
            remaining = _remaining(deadline)
            timeout = httpx.Timeout(
                min(cfg.catalog_download_timeout_seconds, remaining), connect=min(10, remaining)
            )
            async with client.stream("GET", url, headers=headers, timeout=timeout) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise CatalogError("DOWNLOAD_REJECTED", "Catalog redirect has no location")
                    url = url.join(location)
                    if url.scheme != "https":
                        raise CatalogError("DOWNLOAD_REJECTED", "Catalog redirect must use HTTPS")
                    # Never forward API credentials to a redirect destination.
                    headers = {}
                    continue
                if response.status_code in RETRYABLE_STATUS:
                    raise _Retryable()
                if response.status_code != 200:
                    # Status only: the URL may be a signed download link.
                    raise CatalogError(
                        "DOWNLOAD_FAILED", f"Catalog download returned HTTP {response.status_code}"
                    )
                return await _write_limited(response, path, cfg, deadline)
    raise CatalogError("DOWNLOAD_REJECTED", "Too many catalog redirects")


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _Retryable()
    return remaining


async def _write_limited(response, path, cfg, deadline):
    limit = cfg.catalog_download_max_bytes
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise CatalogError(
            "DOWNLOAD_TOO_LARGE", "Catalog download exceeds the configured size limit"
        )
    digest, size = hashlib.sha256(), 0
    partial = path.with_name(path.name + ".part")
    try:
        with open(partial, "wb") as stream:
            # No chunk_size: httpx would otherwise buffer up to that size before
            # yielding, letting a slow trickle of small reads bypass the deadline.
            # Each underlying network read is checked instead.
            async for chunk in response.aiter_bytes():
                _remaining(deadline)
                size += len(chunk)
                if size > limit:
                    raise CatalogError(
                        "DOWNLOAD_TOO_LARGE", "Catalog download exceeds the configured size limit"
                    )
                digest.update(chunk)
                stream.write(chunk)
        _remaining(deadline)
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- validation ------------------------------------------------------------------------------


def read_snapshot(path: Path, expected_count, expected_sha, source_name=None):
    """Validate an approved snapshot completely and return (facts, source, sha). No writes."""
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_sha:
        raise CatalogError(
            "SNAPSHOT_HASH_MISMATCH",
            "Snapshot hash differs; explicitly verify and supply its expected SHA-256",
        )
    try:
        records = json.loads(content, parse_float=Decimal)
    except (ValueError, RecursionError):
        raise CatalogError("SNAPSHOT_MALFORMED", "Snapshot is not valid JSON") from None
    del content
    if not isinstance(records, list) or len(records) != expected_count:
        raise CatalogError(
            "SNAPSHOT_COUNT_MISMATCH",
            "Snapshot count differs; incomplete imports are not published",
        )
    if not records:
        raise CatalogError("SNAPSHOT_EMPTY", "Snapshot contains no products")
    for index, record in enumerate(records):
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("id"), str)
            or not record["id"].strip()
        ):
            raise CatalogError(
                "SNAPSHOT_MALFORMED",
                f"Malformed catalog record #{index}: expected an object with a non-empty string id",
            )
    if len({p["id"] for p in records}) != len(records):
        raise CatalogError("SNAPSHOT_DUPLICATE_IDS", "Duplicate product identifiers")
    source = f"{source_name or path.name}; sha256:{actual}"
    try:
        facts = [_normalize_record(index, p, source) for index, p in enumerate(records)]
    except ValueError as error:
        raise CatalogError("SNAPSHOT_MALFORMED", str(error)) from None
    return facts, source, actual


# --- import ----------------------------------------------------------------------------------


def ingest_file(
    path: Path,
    expected_count=CATALOG_PRODUCT_COUNT,
    expected_sha=CATALOG_SHA256,
    *,
    activate=True,
    carry_withdrawn=True,
):
    """Strict explicit import. Always builds a new generation, even for identical data."""
    with ingestion_lock() as lock:
        facts, source, actual = read_snapshot(path, expected_count, expected_sha)
        if carry_withdrawn:
            facts += _absent_as_withdrawn(facts)
        return publish(
            facts,
            source,
            actual,
            activate=activate,
            lock=lock,
            trim_withdrawn=carry_withdrawn,
            source_product_count=expected_count,
        )


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


def publish(
    facts,
    source,
    source_hash,
    *,
    activate=True,
    lock=None,
    trim_withdrawn=False,
    source_product_count=None,
):
    if not facts or len({p["id"] for p in facts}) != len(facts):
        raise CatalogError("SNAPSHOT_DUPLICATE_IDS", "Empty or duplicate import")
    key = model_key()
    profile = import_profile()
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
    try:
        generated = _embed_missing(key, missing)
    except (CatalogError, psycopg.Error, Problem):
        raise
    except Exception:
        raise CatalogError(
            "EMBEDDING_FAILED", "Embedding generation failed; completed batches remain cached"
        ) from None
    generation = uuid4()
    with connection() as c:
        # One publisher at a time. Errors roll back the generation and pointer together.
        c.execute("SELECT pg_advisory_xact_lock(%s)", (PUBLISH_LOCK_KEY,))
        if lock is not None:
            lock.verify(c)
        c.execute(
            "INSERT INTO catalog_generations(id,source,source_hash,model_key,product_count,"
            "embedding_dimensions,import_profile,source_product_count) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                generation,
                source,
                source_hash,
                key,
                len(facts),
                dimensions(),
                profile,
                len(facts) if source_product_count is None else source_product_count,
            ),
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
                raise CatalogError("PUBLISH_INCOMPLETE", "Incomplete product import")
        if activate:
            _activate(c, generation)
        trimmed = _cleanup(c, WITHDRAWN_LIMIT)["removed"] if activate and trim_withdrawn else 0
    return {
        "generation": str(generation),
        "products": len(facts) - trimmed,
        "withdrawn_products": sum(bool(p["deleted"]) for p in facts) - trimmed,
        "trimmed_withdrawn": trimmed,
        "new_embeddings": generated,
        "reused_embeddings": len(text_by_hash) - generated,
        "active": activate,
        "volume_evidence": dict(Counter(p["measures"]["L"]["status"] for p in facts)),
        "allergen_conflicts": sum(bool(p["allergen_conflicts"]) for p in facts),
        "model": key,
        "import_profile": profile,
        "source_hash": source_hash,
    }


def _embed_missing(key, missing):
    batch_size = settings().embedding_batch_size

    def cache_batch(batch):
        values = embed([t for _, t in batch])
        if len(values) != len(batch) or any(len(v) != dimensions() for v in values):
            raise CatalogError(
                "EMBEDDING_INVALID", "Embedding shape is incompatible with the catalog schema"
            )
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
    return generated


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
        c.execute("SELECT pg_advisory_xact_lock(%s)", (PUBLISH_LOCK_KEY,))
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
        # DIS-012: a staged generation is published inactive (no trim then), so trim on activation.
        trimmed = _cleanup(c, WITHDRAWN_LIMIT)["removed"]
    return {
        "generation": str(generation),
        "products": actual - trimmed,
        "trimmed_withdrawn": trimmed,
        "model": model_key(),
    }


# --- unattended sync -------------------------------------------------------------------------


def active_catalog_state(c):
    row = c.execute(
        "SELECT g.* FROM active_catalog a JOIN catalog_generations g ON g.id=a.generation"
    ).fetchone()
    if not row:
        return None
    stored = c.execute(
        "SELECT count(*) AS n FROM products WHERE generation=%s AND vector_dims(embedding)=%s",
        (row["id"], row["embedding_dimensions"]),
    ).fetchone()["n"]
    return row | {"stored_products": stored}


def rebuild_reason(state, source_hash, expected_count):
    """None only when the active catalog is a complete, compatible build of this snapshot."""
    if state is None:
        return "no_active_catalog"
    if state["source_hash"] != source_hash:
        return "source_changed"
    if state["model_key"] != model_key() or state["embedding_dimensions"] != dimensions():
        return "embedding_profile_changed"
    if state["import_profile"] != import_profile():
        return "import_profile_changed"
    if (
        state["source_product_count"] != expected_count
        or state["stored_products"] != state["product_count"]
    ):
        return "active_catalog_incomplete"
    return None


def sync_catalog(*, file=None, expected_sha=CATALOG_SHA256, expected_count=CATALOG_PRODUCT_COUNT):
    """One unattended run: obtain, validate, skip if current, otherwise import and activate."""
    with ingestion_lock() as lock:
        work_dir = settings().catalog_work_dir or None
        with tempfile.TemporaryDirectory(dir=work_dir, prefix="catalog-sync-") as work:
            if file is None:
                path = Path(work) / SNAPSHOT_NAME
                source_hash = download(path)
            else:
                path = Path(file)
                source_hash = file_sha256(path)
            if source_hash != expected_sha:
                raise CatalogError(
                    "SNAPSHOT_HASH_MISMATCH",
                    "Snapshot hash differs from the approved SHA-256; nothing was imported",
                )
            with connection() as c:
                state = active_catalog_state(c)
            reason = rebuild_reason(state, source_hash, expected_count)
            if reason is None:
                # Byte-identical to the approved snapshot behind a complete, compatible
                # catalog: no parsing, embeddings, product rows or generation.
                return {
                    "outcome": "unchanged",
                    "source_hash": source_hash,
                    "generation": str(state["id"]),
                    "products": state["product_count"],
                    "new_embeddings": 0,
                    "reused_embeddings": 0,
                }
            facts, source, actual = read_snapshot(path, expected_count, expected_sha, SNAPSHOT_NAME)
            facts += _absent_as_withdrawn(facts)
            result = publish(
                facts,
                source,
                actual,
                lock=lock,
                trim_withdrawn=True,
                source_product_count=expected_count,
            )
    return {
        "outcome": "updated",
        "reason": reason,
        "source_hash": result["source_hash"],
        "generation": result["generation"],
        "products": result["products"],
        "withdrawn_products": result["withdrawn_products"],
        "new_embeddings": result["new_embeddings"],
        "reused_embeddings": result["reused_embeddings"],
        "model": result["model"],
        "import_profile": result["import_profile"],
    }


def run_sync(**kwargs):
    """Structured, log-safe result and process exit code for `aimo sync-catalog`."""
    started = time.monotonic()
    code = 0
    try:
        result = sync_catalog(**kwargs)
    except IngestionRunning:
        # The other run owns the outcome; this invocation changed nothing.
        result = {"outcome": "already-running"}
    except CatalogError as error:
        result, code = {"outcome": "failed", "error_code": error.code, "error": str(error)}, 1
    except Problem as error:
        result, code = {"outcome": "failed", "error_code": error.code, "error": error.message}, 1
    except psycopg.Error as error:
        result = {
            "outcome": "failed",
            "error_code": "DATABASE_ERROR",
            "error": f"Database error ({type(error).__name__}); the active catalog is unchanged",
        }
        code = 1
    except Exception as error:  # Never echo exception text: it may contain URLs or data.
        result = {
            "outcome": "failed",
            "error_code": "INTERNAL_ERROR",
            "error": f"Unexpected {type(error).__name__}; the active catalog is unchanged",
        }
        code = 1
    return {
        "event": "catalog_sync",
        **result,
        "duration_seconds": round(time.monotonic() - started, 1),
    }, code


WITHDRAWN_LIMIT = Decimal("0.10")


def cleanup_withdrawn(max_share=None):
    """Remove withdrawn products from the active catalog that no pending proposal includes.

    `max_share=None` (DIS-011, the manual call) removes every unprotected withdrawn product.
    With a share such as `WITHDRAWN_LIMIT` (DIS-012, run at the end of an ingestion publish) it
    removes only the oldest by `withdrawn_since`, one at a time, until withdrawn products are at
    most that share of the stored products of the active generation (all stored products,
    including withdrawn, re-counted after each removal), skipping protected products.

    Pending means the proposal can still be committed or refreshed: no order yet, the current
    revision not rejected, and either live (not denied, not expired) or a saved-recipe proposal,
    which is refreshed in place even when closed. Product ids come from the stored line snapshot.
    History is never touched: proposals, orders and receipts keep their own copy of the facts.
    """
    with connection() as c:
        c.execute("SELECT pg_advisory_xact_lock(893017)")
        return _cleanup(c, max_share)


def _cleanup(c, max_share):
    """Cleanup inside a transaction that already holds the publisher lock."""
    active = c.execute("SELECT generation FROM active_catalog").fetchone()
    if not active:
        return {"removed": 0, "kept_in_use": 0, "removed_ids": []}
    generation = active["generation"]
    rows = c.execute(
        """SELECT id, id IN (SELECT product_id FROM catalog_protected_products)
        AS protected FROM products
        WHERE generation=%s AND facts->'deleted'='true'::jsonb
        ORDER BY withdrawn_since NULLS FIRST, id""",
        (generation,),
    ).fetchall()
    total = c.execute(
        "SELECT count(*) AS n FROM products WHERE generation=%s", (generation,)
    ).fetchone()["n"]
    withdrawn, doomed = len(rows), []
    for row in rows:
        if max_share is not None and Decimal(withdrawn) <= Decimal(total) * max_share:
            break
        if not row["protected"]:
            doomed.append(row["id"])
            withdrawn -= 1
            total -= 1
    if doomed:
        c.execute("DELETE FROM products WHERE generation=%s AND id = ANY(%s)", (generation, doomed))
        c.execute(
            "UPDATE catalog_generations SET product_count=product_count-%s WHERE id=%s",
            (len(doomed), generation),
        )
    return {"removed": len(doomed), "kept_in_use": withdrawn, "removed_ids": sorted(doomed)}
