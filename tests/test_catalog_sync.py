"""Unattended `aimo sync-catalog`: skip unchanged data, rebuild only when needed, never expose a
partial catalog, coordinate concurrent runs, and keep serving consistent while it publishes.

Synthetic snapshots, mocked suppliers and loopback HTTP only; no model or real data.
The shared fixture catalog is restored after every test.
"""

import asyncio
import hashlib
import json
import socketserver
import threading
import time
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_ingest import raw_product

import aimo.ingest as ingestion
from aimo.config import settings
from aimo.db import Problem, close_pools, connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import CatalogError, ingestion_lock, publish, run_sync, sync_catalog
from aimo.permissions import configure_catalog_sync_role
from aimo.schemas import PrepareRequest, SearchRequest
from aimo.search import search_products


@pytest.fixture(autouse=True)
def restore_fixture_catalog():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


def snapshot(tmp_path, records, name="snapshot.json"):
    path = tmp_path / name
    content = json.dumps(records).encode()
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def products(n=3, tag=None):
    tag = tag or uuid4().hex  # unique texts: the embedding cache persists between runs
    return [raw_product(f"sync-{i}", f"Synthetic {tag} item {i} 1 l") for i in range(n)]


def sync(path, sha, count, **kw):
    return sync_catalog(file=path, expected_sha=sha, expected_count=count, **kw)


def counts():
    with connection() as c:
        return (
            c.execute("SELECT count(*) AS n FROM catalog_generations").fetchone()["n"],
            c.execute("SELECT count(*) AS n FROM products").fetchone()["n"],
        )


def active_id():
    with connection() as c:
        row = c.execute("SELECT generation FROM active_catalog").fetchone()
    return str(row["generation"]) if row else None


def count_embeds(monkeypatch, fail_after=None):
    calls = []
    real = ingestion.embed

    def wrapped(texts):
        if fail_after is not None and len(calls) >= fail_after:
            raise RuntimeError("injected provider outage with secret-looking detail")
        calls.append(len(texts))
        return real(texts)

    monkeypatch.setattr(ingestion, "embed", wrapped)
    return calls


def tune(monkeypatch, **updates):
    cfg = settings().model_copy(update=updates)
    monkeypatch.setattr(ingestion, "settings", lambda: cfg)
    return cfg


# --- skipping and rebuilding -----------------------------------------------------------------


def test_initial_sync_without_an_active_catalog_imports_and_activates(tmp_path):
    with connection() as c:
        c.execute("DELETE FROM active_catalog")
    path, sha = snapshot(tmp_path, products(3))
    result = sync(path, sha, 3)
    assert result["outcome"] == "updated" and result["reason"] == "no_active_catalog"
    assert result["products"] == 3 and result["new_embeddings"] == 3
    assert active_id() == result["generation"]
    with connection() as c:
        row = c.execute(
            "SELECT source, source_hash, import_profile FROM catalog_generations WHERE id=%s",
            (result["generation"],),
        ).fetchone()
    # Provenance uses the stable snapshot name, not the temporary download location.
    assert row["source"] == f"{ingestion.SNAPSHOT_NAME}; sha256:{sha}"
    assert row["source_hash"] == sha and row["import_profile"] == ingestion.import_profile()


def test_identical_rerun_creates_no_generation_and_requests_no_embeddings(tmp_path, monkeypatch):
    path, sha = snapshot(tmp_path, products(4))
    first = sync(path, sha, 4)
    before = counts()
    calls = count_embeds(monkeypatch)
    result, code = run_sync(file=path, expected_sha=sha, expected_count=4)
    assert code == 0 and result["event"] == "catalog_sync"
    assert result["outcome"] == "unchanged" and result["generation"] == first["generation"]
    assert result["new_embeddings"] == 0 and result["products"] == 4
    assert result["source_hash"] == sha and "duration_seconds" in result
    assert calls == [] and counts() == before and active_id() == first["generation"]


def test_changed_snapshot_needs_explicit_approval_then_reuses_embeddings(tmp_path):
    tag = uuid4().hex
    approved, approved_sha = snapshot(tmp_path, products(3, tag), "a.json")
    first = sync(approved, approved_sha, 3)
    changed_records = products(3, tag) + [raw_product("sync-new", f"Added {tag} 2 dl")]
    changed, changed_sha = snapshot(tmp_path, changed_records, "b.json")
    # Supplier data that was never approved is refused; serving is untouched.
    result, code = run_sync(file=changed, expected_sha=approved_sha, expected_count=3)
    assert code == 1 and result["error_code"] == "SNAPSHOT_HASH_MISMATCH"
    assert active_id() == first["generation"]
    # The explicitly validated path accepts it with its own expected hash and count.
    updated = sync(changed, changed_sha, 4)
    assert updated["outcome"] == "updated" and updated["reason"] == "source_changed"
    assert updated["new_embeddings"] == 1 and updated["reused_embeddings"] == 3
    assert active_id() == updated["generation"]


def test_embedding_profile_change_rebuilds_instead_of_skipping(tmp_path, monkeypatch):
    path, sha = snapshot(tmp_path, products(2))
    sync(path, sha, 2)
    monkeypatch.setattr(ingestion, "model_key", lambda: "fixture-hash-v2-test:384")
    result = sync(path, sha, 2)
    assert result["reason"] == "embedding_profile_changed"
    assert result["model"] == "fixture-hash-v2-test:384" and result["new_embeddings"] == 2


def test_import_profile_change_rebuilds_and_reuses_cached_embeddings(tmp_path, monkeypatch):
    path, sha = snapshot(tmp_path, products(3))
    first = sync(path, sha, 3)
    monkeypatch.setattr(ingestion, "import_profile", lambda: "catalog-import-v1:changed")
    result = sync(path, sha, 3)
    assert (
        result["reason"] == "import_profile_changed" and result["generation"] != first["generation"]
    )
    assert result["new_embeddings"] == 0 and result["reused_embeddings"] == 3


def test_legacy_generation_without_a_recorded_profile_is_rebuilt_once(tmp_path):
    path, sha = snapshot(tmp_path, products(2))
    first = sync(path, sha, 2)
    with connection() as c:
        c.execute(
            "UPDATE catalog_generations SET import_profile=NULL WHERE id=%s",
            (first["generation"],),
        )
    assert sync(path, sha, 2)["reason"] == "import_profile_changed"
    assert sync(path, sha, 2)["outcome"] == "unchanged"


def test_import_profile_tracks_normalization_and_document_code(monkeypatch):
    ingestion.import_profile.cache_clear()
    base = ingestion.import_profile()
    version = ingestion.IMPORT_PROFILE_VERSION
    assert base.startswith(f"catalog-import-v{version}:")
    try:
        monkeypatch.setattr(ingestion, "document_text", lambda facts: "different document code")
        ingestion.import_profile.cache_clear()
        assert ingestion.import_profile() != base
        monkeypatch.undo()
        monkeypatch.setattr(ingestion, "IMPORT_PROFILE_VERSION", version + 1)
        ingestion.import_profile.cache_clear()
        assert ingestion.import_profile().startswith(f"catalog-import-v{version + 1}:")
    finally:
        monkeypatch.undo()
        ingestion.import_profile.cache_clear()
    assert ingestion.import_profile() == base


def test_incomplete_active_catalog_is_rebuilt_not_skipped(tmp_path):
    path, sha = snapshot(tmp_path, products(3))
    first = sync(path, sha, 3)
    with connection() as c:
        c.execute(
            "DELETE FROM products WHERE generation=%s AND id='sync-0'", (first["generation"],)
        )
    result = sync(path, sha, 3)
    assert result["reason"] == "active_catalog_incomplete"
    assert result["generation"] != first["generation"] and result["products"] == 3


# --- invalid input and failures preserve serving ---------------------------------------------


def _invalid(kind, tmp_path):
    good = products(2)
    if kind == "hash":
        path, _ = snapshot(tmp_path, good)
        return path, "0" * 64, 2
    if kind == "count":
        path, sha = snapshot(tmp_path, good)
        return path, sha, 3
    if kind == "json":
        path = tmp_path / "broken.json"
        path.write_bytes(b'[{"id": "x"')
        return path, hashlib.sha256(path.read_bytes()).hexdigest(), 1
    records = {
        "not-a-list": {"products": good},
        "empty": [],
        "duplicates": [good[0], good[0]],
        "missing-id": [good[0], {**good[1], "id": ""}],
        "schema": [good[0], {**good[1], "units": "not-a-list"}],
    }[kind]
    path, sha = snapshot(tmp_path, records)
    return path, sha, (len(records) if kind != "not-a-list" else 1)


@pytest.mark.parametrize(
    "kind,code",
    [
        ("hash", "SNAPSHOT_HASH_MISMATCH"),
        ("count", "SNAPSHOT_COUNT_MISMATCH"),
        ("json", "SNAPSHOT_MALFORMED"),
        ("not-a-list", "SNAPSHOT_COUNT_MISMATCH"),
        ("empty", "SNAPSHOT_EMPTY"),
        ("duplicates", "SNAPSHOT_DUPLICATE_IDS"),
        ("missing-id", "SNAPSHOT_MALFORMED"),
        ("schema", "SNAPSHOT_MALFORMED"),
    ],
)
def test_invalid_snapshots_fail_without_replacing_the_active_catalog(tmp_path, kind, code):
    before_active, before_counts = active_id(), counts()
    path, sha, count = _invalid(kind, tmp_path)
    result, exit_code = run_sync(file=path, expected_sha=sha, expected_count=count)
    assert exit_code == 1 and result["outcome"] == "failed" and result["error_code"] == code
    assert active_id() == before_active and counts() == before_counts


def test_embedding_failure_keeps_serving_and_retry_reuses_completed_batches(
    tmp_path, monkeypatch, agent
):
    tune(monkeypatch, embedding_batch_size=2)
    before = active_id()
    path, sha = snapshot(tmp_path, products(6))
    real = ingestion.embed
    calls = count_embeds(monkeypatch, fail_after=2)
    result, code = run_sync(file=path, expected_sha=sha, expected_count=6)
    assert code == 1 and result["error_code"] == "EMBEDDING_FAILED"
    assert "secret-looking" not in json.dumps(result)
    assert calls == [2, 2] and active_id() == before
    # Discovery keeps working against the previous catalog.
    assert search_products(agent, SearchRequest(query="464306"))["generation"] == before
    monkeypatch.setattr(ingestion, "embed", real)
    retry = sync(path, sha, 6)
    assert retry["outcome"] == "updated"
    assert retry["new_embeddings"] == 2
    # Carry-forward withdrawn products reuse the existing fixture embeddings too.
    assert retry["reused_embeddings"] == 4 + len(fixture_facts())


# --- download --------------------------------------------------------------------------------


async def async_chunks(*chunks):
    for chunk in chunks:
        yield chunk


def mock_supplier(monkeypatch, handler, **updates):
    tune(
        monkeypatch,
        valio_aimo_api_key="test-key-not-real",
        valio_aimo_base_url="https://api.test",
        **updates,
    )
    real = httpx.AsyncClient
    monkeypatch.setattr(
        ingestion.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(ingestion, "_sleep", lambda seconds: None)


def test_scheduled_download_path_imports_once_then_skips(tmp_path, monkeypatch):
    content = json.dumps(products(3)).encode()
    sha = hashlib.sha256(content).hexdigest()
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "api.test":
            return httpx.Response(302, headers={"location": "https://files.test/s.json?sig=abc"})
        return httpx.Response(200, content=content)

    mock_supplier(monkeypatch, handler, catalog_work_dir=str(tmp_path))
    first, code = run_sync(expected_sha=sha, expected_count=3)
    assert code == 0 and first["outcome"] == "updated"
    second, code = run_sync(expected_sha=sha, expected_count=3)
    assert code == 0 and second["outcome"] == "unchanged"
    assert seen == ["api.test", "files.test"] * 2
    assert list(tmp_path.iterdir()) == []  # temporary download removed after each run


def test_download_failure_keeps_serving_and_never_logs_the_signed_url(tmp_path, monkeypatch, agent):
    attempts = []

    def handler(request):
        attempts.append(request.url.host)
        if request.url.host == "api.test":
            return httpx.Response(302, headers={"location": "https://files.test/s.json?sig=SECRET"})
        return httpx.Response(503)

    mock_supplier(monkeypatch, handler, catalog_download_attempts=3)
    before = active_id()
    result, code = run_sync(expected_sha="0" * 64, expected_count=1)
    assert code == 1 and result["error_code"] == "DOWNLOAD_FAILED"
    assert "SECRET" not in json.dumps(result) and "files.test" not in json.dumps(result)
    assert attempts == ["api.test", "files.test"] * 3  # bounded retries, each from the start
    assert active_id() == before
    assert search_products(agent, SearchRequest(query="464306"))["products"]


def test_transport_errors_are_retried_then_succeed(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, content=b"[]")

    mock_supplier(monkeypatch, handler)
    assert ingestion.download(tmp_path / "s.json") == hashlib.sha256(b"[]").hexdigest()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "response,code",
    [
        (lambda r: httpx.Response(200, content=b"x" * 11), "DOWNLOAD_TOO_LARGE"),
        (
            lambda r: httpx.Response(200, content=async_chunks(b"x" * 6, b"x" * 6)),
            "DOWNLOAD_TOO_LARGE",
        ),
        (lambda r: httpx.Response(302), "DOWNLOAD_REJECTED"),
        (lambda r: httpx.Response(302, headers={"location": "/again"}), "DOWNLOAD_REJECTED"),
        (lambda r: httpx.Response(404), "DOWNLOAD_FAILED"),
    ],
    ids=["declared-size", "streamed-size", "no-location", "redirect-loop", "not-found"],
)
def test_download_bounds_leave_no_partial_file(tmp_path, monkeypatch, response, code):
    mock_supplier(monkeypatch, response, catalog_download_max_bytes=10)
    out = tmp_path / "s.json"
    with pytest.raises(CatalogError) as failure:
        ingestion.download(out)
    assert failure.value.code == code
    assert list(tmp_path.iterdir()) == []


def test_download_deadline_is_bounded(tmp_path, monkeypatch):
    mock_supplier(
        monkeypatch,
        lambda r: httpx.Response(200, content=b"[]"),
        catalog_download_deadline_seconds=1e-9,
        catalog_download_attempts=2,
    )
    with pytest.raises(CatalogError, match="bounded retries"):
        ingestion.download(tmp_path / "s.json")


def test_slow_trickle_of_small_chunks_cannot_outlast_the_deadline(tmp_path, monkeypatch):
    async def trickle():
        for _ in range(100):  # 5 s of 100-byte chunks, never idle long enough to time out
            await asyncio.sleep(0.05)
            yield b"x" * 100

    mock_supplier(
        monkeypatch,
        lambda r: httpx.Response(200, content=trickle()),
        catalog_download_deadline_seconds=0.5,
        catalog_download_attempts=1,
    )
    started = time.monotonic()
    with pytest.raises(CatalogError) as failure:
        ingestion.download(tmp_path / "s.json")
    assert failure.value.code == "DOWNLOAD_FAILED"
    assert time.monotonic() - started < 1.5  # aborted near the deadline, not after 5 s
    assert list(tmp_path.iterdir()) == []


def test_each_request_read_timeout_is_capped_by_the_remaining_deadline(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, content=b"[]")

    mock_supplier(monkeypatch, handler, catalog_download_deadline_seconds=5)
    ingestion.download(tmp_path / "s.json")
    assert 0 < seen[0]["read"] <= 5 and seen[0]["connect"] <= 5


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_cancelled_attempt_finishes_cleanup_before_retry(tmp_path, monkeypatch, stage):
    requests, cancelled = [], []
    out = tmp_path / "s.json"

    async def stall():
        try:
            await asyncio.sleep(2)
        finally:
            cancelled.append(stage)

    async def body():
        yield b"partial"
        await stall()

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            if stage == "headers":
                await stall()
            return httpx.Response(200, content=body())
        assert cancelled == [stage]
        assert not out.with_name("s.json.part").exists()
        return httpx.Response(200, content=b"[]")

    mock_supplier(
        monkeypatch,
        handler,
        catalog_download_deadline_seconds=0.05,
        catalog_download_attempts=2,
    )
    assert ingestion.download(out) == hashlib.sha256(b"[]").hexdigest()
    assert out.read_bytes() == b"[]"
    assert len(requests) == 2 and requests[0].url == requests[1].url
    assert list(tmp_path.iterdir()) == [out]


@pytest.mark.parametrize("stage", ["headers", "redirect-headers", "body"])
def test_deadline_cancels_trickling_network_reads(tmp_path, monkeypatch, stage):
    disconnected = threading.Event()
    requests = []

    class Supplier(socketserver.BaseRequestHandler):
        def handle(self):
            request = self.request.recv(65536)
            requests.append(request)
            try:
                if stage == "redirect-headers" and b"/api/products/download " in request:
                    self.request.sendall(b"HTTP/1.1 302 Found\r\nLocation: /file\r\n\r\n")
                    return
                self.request.sendall(b"HTTP/1.1 200 OK\r\n")
                if stage == "body":
                    self.request.sendall(b"Content-Length: 100\r\n\r\nx")
                # Frequent reads keep the idle timeout from firing for two seconds.
                for _ in range(40):
                    time.sleep(0.05)
                    self.request.sendall(b"x" if stage == "body" else b"X-Trickle: x\r\n")
            except OSError:
                disconnected.set()

    with socketserver.TCPServer(("127.0.0.1", 0), Supplier) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        worker.start()
        tune(
            monkeypatch,
            valio_aimo_api_key="synthetic-loopback-key",
            valio_aimo_base_url=f"https://127.0.0.1:{server.server_address[1]}",
            catalog_download_deadline_seconds=0.25,
            catalog_download_timeout_seconds=0.25,
            catalog_download_attempts=1,
        )
        real = httpx.AsyncClient

        async def loopback(request):
            # Exercise the real HTTP transport locally, with no TLS fixture required.
            request.url = request.url.copy_with(scheme="http")

        monkeypatch.setattr(
            ingestion.httpx,
            "AsyncClient",
            lambda **kw: real(event_hooks={"request": [loopback]}, trust_env=False, **kw),
        )
        try:
            started = time.monotonic()
            with pytest.raises(CatalogError) as failure:
                ingestion.download(tmp_path / "s.json")
            assert failure.value.code == "DOWNLOAD_FAILED"
            assert time.monotonic() - started < 1.25
            assert disconnected.wait(0.5), "the timed-out socket must be closed"
            assert len(requests) == (2 if stage == "redirect-headers" else 1)
            if stage == "redirect-headers":
                assert b"x-api-key:" not in requests[1].lower()
            assert list(tmp_path.iterdir()) == []
        finally:
            server.shutdown()
            worker.join(timeout=3)


def test_second_redirect_hop_must_stay_https(tmp_path, monkeypatch):
    def handler(request):
        if request.url.host == "api.test":
            return httpx.Response(302, headers={"location": "https://cdn.test/a"})
        assert "x-api-key" not in request.headers
        return httpx.Response(302, headers={"location": "http://cdn.test/b"})

    mock_supplier(monkeypatch, handler)
    with pytest.raises(CatalogError, match="HTTPS"):
        ingestion.download(tmp_path / "s.json")


def test_plain_http_supplier_base_url_is_refused(tmp_path, monkeypatch):
    mock_supplier(monkeypatch, lambda r: pytest.fail("no request over plain HTTP"))
    tune(monkeypatch, valio_aimo_api_key="k", valio_aimo_base_url="http://api.test")
    with pytest.raises(CatalogError, match="HTTPS"):
        ingestion.download(tmp_path / "s.json")


# --- coordination ----------------------------------------------------------------------------


def test_manual_and_scheduled_runs_are_coordinated_by_the_database(tmp_path, monkeypatch):
    content = json.dumps(products(2)).encode()
    sha = hashlib.sha256(content).hexdigest()
    started, release = threading.Event(), threading.Event()

    def slow_download(path):
        started.set()
        assert release.wait(10)
        path.write_bytes(content)
        return sha

    monkeypatch.setattr(ingestion, "download", slow_download)
    outcome = {}
    scheduled = threading.Thread(
        target=lambda: outcome.update(run_sync(expected_sha=sha, expected_count=2)[0])
    )
    scheduled.start()
    try:
        assert started.wait(10)
        manual, code = run_sync(expected_sha=sha, expected_count=2)
        assert code == 0 and manual["outcome"] == "already-running"
        # The strict explicit import is coordinated by the same lock.
        with pytest.raises(ingestion.IngestionRunning):
            ingestion.ingest_file(tmp_path / "unused.json", 2, sha)
    finally:
        release.set()
        scheduled.join(10)
    assert outcome["outcome"] == "updated"


def test_lost_lock_prevents_publication_and_keeps_completed_embeddings(tmp_path, monkeypatch):
    before = active_id()
    path, sha = snapshot(tmp_path, products(3))
    real = ingestion.embed

    def embed_then_lose_lock(texts):
        with psycopg.connect(settings().database_url, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name='aimo-catalog-ingestion'"
            )
        return real(texts)

    monkeypatch.setattr(ingestion, "embed", embed_then_lose_lock)
    result, code = run_sync(file=path, expected_sha=sha, expected_count=3)
    assert code == 1 and result["error_code"] == "LOCK_LOST"
    assert active_id() == before
    monkeypatch.setattr(ingestion, "embed", real)
    retry = sync(path, sha, 3)
    assert retry["outcome"] == "updated" and retry["new_embeddings"] == 0


def test_lock_holder_blocks_other_runs_until_released():
    with ingestion_lock():
        result, code = run_sync(file="unused", expected_sha="0" * 64, expected_count=1)
        assert (result["outcome"], code) == ("already-running", 0)
    with ingestion_lock():
        pass  # released on exit


def test_unreachable_database_is_a_safe_failure(monkeypatch):
    tune(monkeypatch, database_url="postgresql://nobody:secret-pw@127.0.0.1:1/none")
    result, code = run_sync(file="unused", expected_sha="0" * 64, expected_count=1)
    assert code == 1 and result["error_code"] == "DATABASE_UNAVAILABLE"
    assert "secret-pw" not in json.dumps(result)


@pytest.mark.parametrize(
    "error,code",
    [
        (
            Problem("DATABASE_BUSY", "Database capacity is temporarily unavailable.", 503),
            "DATABASE_BUSY",
        ),
        (psycopg.errors.InsufficientPrivilege("permission denied for table x"), "DATABASE_ERROR"),
        (KeyError("https://signed.example/?sig=SECRET"), "INTERNAL_ERROR"),
    ],
)
def test_unexpected_errors_are_reported_with_codes_only(monkeypatch, error, code):
    def boom(**kw):
        raise error

    monkeypatch.setattr(ingestion, "sync_catalog", boom)
    result, exit_code = run_sync()
    assert exit_code == 1 and result["error_code"] == code
    assert "SECRET" not in json.dumps(result)


# --- serving while ingestion runs ------------------------------------------------------------


def test_search_snapshot_stays_consistent_while_sync_activates_and_prunes(
    tmp_path, monkeypatch, agent
):
    import aimo.search as search

    tune(monkeypatch, catalog_generations_to_keep=1)  # prune the old catalog immediately
    old = active_id()
    fixture_ids = {p["id"] for p in fixture_facts()}
    path, sha = snapshot(tmp_path, products(3))
    real = search.embed
    swapped = {}

    def embed_while_publishing(texts, query=False):
        if not swapped:
            swapped.update(sync(path, sha, 3))
            with connection() as c:
                assert (
                    c.execute(
                        "SELECT count(*) AS n FROM products WHERE generation=%s", (old,)
                    ).fetchone()["n"]
                    == 0
                )
        return real(texts, query=query)

    monkeypatch.setattr(search, "embed", embed_while_publishing)
    # This search's transaction began before activation; its semantic stage runs after the
    # new catalog was activated and the old rows were deleted.
    inflight = search_products(agent, SearchRequest(query="lactose free milk"), "semantic")
    assert swapped["outcome"] == "updated"
    assert inflight["generation"] == old
    assert inflight["products"] and {p["id"] for p in inflight["products"]} <= fixture_ids
    after = search_products(agent, SearchRequest(query="Synthetic item"), "keyword")
    assert after["generation"] == swapped["generation"]
    assert after["products"]
    assert {p["id"] for p in after["products"]} <= {"sync-0", "sync-1", "sync-2"}


def test_inflight_purchase_is_revalidated_against_the_newly_synced_catalog(
    tmp_path, service, agent, request_data
):
    from test_hardening import commit

    proposal = service.prepare_order(agent, PrepareRequest(**request_data))
    path, sha = snapshot(tmp_path, [raw_product("464306", deleted=True), *products(1)])
    assert sync(path, sha, 2)["outcome"] == "updated"
    revised = service.commit_order(agent, commit(proposal))
    assert revised["status"] == "revised" and revised["policy_outcome"] == "denied"
    assert "PRODUCT_DELETED" in {r["code"] for r in revised["reasons"]}
    with connection() as c:
        original = c.execute(
            "SELECT snapshot FROM proposal_revisions WHERE proposal_id=%s AND revision=1",
            (proposal["proposal_id"],),
        ).fetchone()
    assert original is not None  # historical purchasing records survive catalog replacement


# --- least privilege -------------------------------------------------------------------------


def test_dedicated_catalog_role_can_sync_but_cannot_read_purchasing_data(
    tmp_path, monkeypatch, service, agent, request_data
):
    # A pending purchase protects its withdrawn catalog IDs even for the restricted sync role.
    service.prepare_order(agent, PrepareRequest(**request_data))
    protected_ids = {line["product_id"] for line in request_data["lines"]}
    role = "catalog_sync_test_" + uuid4().hex[:12]
    password = uuid4().hex
    admin_url = settings().database_url
    with psycopg.connect(admin_url, autocommit=True) as admin:
        if not admin.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]:
            pytest.skip("Restricted-role integration test requires CREATEROLE")
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        # Even a role that once had broad grants converges to the catalog tables only.
        admin.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(role)
            )
        )
        configure_catalog_sync_role(admin, role)
        configure_catalog_sync_role(admin, role)
    url = make_conninfo(admin_url, user=role, password=password)
    try:
        monkeypatch.setenv("DATABASE_URL", url)
        settings.cache_clear()
        path, sha = snapshot(tmp_path, products(2))
        result, code = run_sync(file=path, expected_sha=sha, expected_count=2)
        assert code == 0 and result["outcome"] == "updated"
        assert run_sync(file=path, expected_sha=sha, expected_count=2)[0]["outcome"] == "unchanged"
        with psycopg.connect(url, autocommit=True) as restricted:
            retained = restricted.execute(
                "SELECT id FROM products WHERE generation=%s AND facts->'deleted'='true'::jsonb",
                (result["generation"],),
            ).fetchall()
            assert protected_ids <= {row[0] for row in retained}
            for statement in (
                "SELECT * FROM sessions",
                "SELECT * FROM identities",
                "SELECT * FROM orders",
                "SELECT * FROM proposal_revisions",
                "SELECT * FROM schema_migrations",
                "DELETE FROM catalog_generations",
                "UPDATE products SET facts=facts",
                "UPDATE catalog_generations SET source_hash=source_hash",
                "CREATE TABLE forbidden_catalog_table(id int)",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    restricted.execute(statement)
    finally:
        monkeypatch.undo()
        settings.cache_clear()
        close_pools()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_sync_retains_withdrawn_products_and_skips_identical_snapshot(tmp_path):
    with connection() as c:
        c.execute("DELETE FROM active_catalog")
    records = products(60, tag="withdrawal-integration")
    first_path, first_sha = snapshot(tmp_path, records, "before.json")
    sync(first_path, first_sha, len(records))
    second_path, second_sha = snapshot(tmp_path, records[1:], "after.json")
    result = sync(second_path, second_sha, len(records) - 1)
    with connection() as c:
        withdrawn = c.execute(
            "SELECT facts, withdrawn_since FROM products WHERE generation=%s AND id=%s",
            (result["generation"], records[0]["id"]),
        ).fetchone()
        assert withdrawn["facts"]["deleted"] and withdrawn["withdrawn_since"] is not None
        state = c.execute(
            "SELECT source_product_count, product_count FROM catalog_generations WHERE id=%s",
            (result["generation"],),
        ).fetchone()
        assert state["source_product_count"] == len(records) - 1
        assert state["product_count"] == result["products"] == len(records)
    assert sync(second_path, second_sha, len(records) - 1)["outcome"] == "unchanged"


def test_legacy_generation_without_source_count_rebuilds_once(tmp_path):
    path, sha = snapshot(tmp_path, products(3))
    first = sync(path, sha, 3)
    with connection() as c:
        c.execute(
            "UPDATE catalog_generations SET source_product_count=NULL WHERE id=%s",
            (first["generation"],),
        )
    assert sync(path, sha, 3)["reason"] == "active_catalog_incomplete"
    assert sync(path, sha, 3)["outcome"] == "unchanged"
