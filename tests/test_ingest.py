"""Catalog snapshot download and import: integrity checks and atomic publication.

Everything runs against a synthetic snapshot in tmp_path and httpx.MockTransport; the real network
and the real catalog in data/ are never touched. The shared fixture catalog is restored afterwards.
"""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

import aimo.ingest as ingestion
from aimo.config import Settings
from aimo.db import connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import CatalogError, download, ingest_file, publish


@pytest.fixture(autouse=True)
def restore_fixture_catalog():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


def raw_product(pid, name="Synthetic milk 1 l", **extra):
    return {
        "id": pid,
        "salesUnit": "ST",
        "baseUnit": "ST",
        "allowedLotSize": "1",
        "units": [{"unitId": "ST", "sizeInBaseUnits": 1}],
        "synkkaData": {
            "names": [{"language": "en", "value": name}],
            "variableUnit": False,
            "classifications": [],
            "unitConversions": [
                {
                    "synkkaPackagingType": "BASE_UNIT_OR_EACH",
                    "volume": {"unit": "LTR", "value": 1},
                }
            ],
        },
        **extra,
    }


def write_snapshot(tmp_path, records):
    path = tmp_path / "snapshot.json"
    content = json.dumps(records).encode()
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def active():
    with connection() as c:
        row = c.execute(
            "SELECT g.id, g.source, g.product_count FROM active_catalog a "
            "JOIN catalog_generations g ON g.id=a.generation"
        ).fetchone()
        ids = {
            r["id"] for r in c.execute("SELECT id FROM products WHERE generation=%s", (row["id"],))
        }
    return row, ids


def test_ingest_file_keeps_withdrawn_products_for_exact_denial(tmp_path):
    records = [
        raw_product("t-1"),
        raw_product("t-2", "Synthetic cream 2 dl"),
        raw_product("t-gone", deleted=True),
    ]
    path, sha = write_snapshot(tmp_path, records)
    result = ingest_file(path, 3, sha)
    # Withdrawn products stay in the snapshot so a lookup can be denied exactly; discovery hides them.
    assert result["products"] == 3
    assert result["withdrawn_products"] == 1
    assert result["source_hash"] == sha
    assert result["volume_evidence"] == {"known": 2, "conflicting": 1}  # "2 dl" name vs 1 L data
    row, ids = active()
    assert str(row["id"]) == result["generation"]
    assert ids == {"t-1", "t-2", "t-gone"}
    assert row["source"] == f"snapshot.json; sha256:{sha}"
    assert row["product_count"] == 3
    with connection() as c:
        flags = {
            r["id"]: r["deleted"]
            for r in c.execute(
                "SELECT id, COALESCE((facts->>'deleted')::boolean,false) AS deleted FROM products WHERE generation=%s",
                (row["id"],),
            )
        }
    assert flags == {"t-1": False, "t-2": False, "t-gone": True}


def test_ingest_file_reuses_embeddings_on_second_import(tmp_path):
    path, sha = write_snapshot(tmp_path, [raw_product("t-1"), raw_product("t-2", "Other 1 l")])
    first = ingest_file(path, 2, sha)
    second = ingest_file(path, 2, sha)
    assert first["generation"] != second["generation"]
    assert second["new_embeddings"] == 0
    assert second["reused_embeddings"] == 2


def test_hash_mismatch_is_refused_and_active_catalog_unchanged(tmp_path):
    before, _ = active()
    path, _ = write_snapshot(tmp_path, [raw_product("t-1")])
    with pytest.raises(ValueError, match="hash differs"):
        ingest_file(path, 1, "0" * 64)
    assert active()[0]["id"] == before["id"]


def test_count_mismatch_is_refused(tmp_path):
    path, sha = write_snapshot(tmp_path, [raw_product("t-1"), raw_product("t-2")])
    with pytest.raises(ValueError, match="count differs"):
        ingest_file(path, 3, sha)


def test_non_list_snapshot_is_refused(tmp_path):
    path, sha = write_snapshot(tmp_path, {"products": []})
    with pytest.raises(ValueError, match="count differs"):
        ingest_file(path, 1, sha)


def test_duplicate_identifiers_are_refused(tmp_path):
    path, sha = write_snapshot(tmp_path, [raw_product("t-1"), raw_product("t-1")])
    with pytest.raises(ValueError, match="Duplicate product identifiers"):
        ingest_file(path, 2, sha)


def test_snapshot_of_only_withdrawn_products_publishes_them_as_withdrawn(tmp_path):
    path, sha = write_snapshot(tmp_path, [raw_product("t-1", deleted=True)])
    result = ingest_file(path, 1, sha)
    assert result["products"] == 1 and result["withdrawn_products"] == 1
    assert active()[1] == {"t-1"}


def test_publish_rejects_duplicate_ids_and_wrong_embedding_shape(monkeypatch):
    data = fixture_facts()
    with pytest.raises(ValueError, match="Empty or duplicate import"):
        publish(data + [deepcopy(data[0])], "dup", "h")
    changed = deepcopy(data)
    changed[0]["names"]["en"] = "an embedding-shape probe string"
    monkeypatch.setattr(ingestion, "embed", lambda texts: [[0.0] * 3 for _ in texts])
    before, _ = active()
    with pytest.raises(ValueError, match="Embedding shape"):
        publish(changed, "bad-shape", "h")
    assert active()[0]["id"] == before["id"]


def test_publish_rejects_wrong_number_of_vectors(monkeypatch):
    changed = fixture_facts()
    changed[0]["names"]["en"] = "another unseen embedding probe"
    monkeypatch.setattr(ingestion, "embed", lambda texts: [])
    with pytest.raises(ValueError, match="Embedding shape"):
        publish(changed, "no-vectors", "h")


# --- download ------------------------------------------------------------------------------------


def configure(monkeypatch, handler, key="test-key-not-real"):
    cfg = Settings(_env_file=None, valio_aimo_api_key=key, valio_aimo_base_url="https://api.test")
    monkeypatch.setattr(ingestion, "settings", lambda: cfg)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        ingestion.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


def test_download_requires_an_api_key(monkeypatch, tmp_path):
    configure(monkeypatch, lambda request: pytest.fail("no request without a key"), key="")
    with pytest.raises(ValueError, match="VALIO_AIMO_API_KEY is required"):
        download(tmp_path / "out.json")


def test_download_sends_key_and_writes_body(monkeypatch, tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b'[{"id":"x"}]')

    configure(monkeypatch, handler)
    out = tmp_path / "out.json"
    download(out)
    assert out.read_bytes() == b'[{"id":"x"}]'
    assert str(seen[0].url) == "https://api.test/api/products/download"
    assert seen[0].headers["x-api-key"] == "test-key-not-real"


def test_download_follows_https_redirect_without_forwarding_the_key(monkeypatch, tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "api.test":
            return httpx.Response(302, headers={"location": "https://files.test/snap.json"})
        return httpx.Response(200, content=b"[]")

    configure(monkeypatch, handler)
    out = tmp_path / "out.json"
    download(out)
    assert out.read_bytes() == b"[]"
    assert [r.url.host for r in seen] == ["api.test", "files.test"]
    assert "x-api-key" not in seen[1].headers


def test_download_resolves_a_relative_redirect_against_the_base_url(monkeypatch, tmp_path):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/api/products/download":
            return httpx.Response(307, headers={"location": "/files/snap.json"})
        return httpx.Response(200, content=b"[1]")

    configure(monkeypatch, handler)
    download(tmp_path / "out.json")
    assert seen[-1] == "https://api.test/files/snap.json"


def test_download_refuses_a_non_https_redirect(monkeypatch, tmp_path):
    def handler(request):
        if request.url.host == "api.test":
            return httpx.Response(302, headers={"location": "http://files.test/snap.json"})
        pytest.fail("the insecure redirect target must not be requested")

    configure(monkeypatch, handler)
    out = tmp_path / "out.json"
    with pytest.raises(ValueError, match="must use HTTPS"):
        download(out)
    assert not out.exists()


def test_download_http_error_leaves_no_file(monkeypatch, tmp_path):
    configure(monkeypatch, lambda request: httpx.Response(403))
    out = tmp_path / "out.json"
    with pytest.raises(CatalogError, match="HTTP 403") as failure:
        download(out)
    assert failure.value.code == "DOWNLOAD_FAILED"
    assert not out.exists()


def test_large_import_embeds_in_batches_of_128(tmp_path, capsys):
    run = uuid4().hex  # unique texts: the embedding cache persists between test runs
    records = [raw_product(f"bulk-{i:03d}", f"Synthetic {run} number {i}") for i in range(130)]
    path, sha = write_snapshot(tmp_path, records)
    result = ingest_file(path, 130, sha)
    assert result["products"] == 130 and result["new_embeddings"] == 130
    out = capsys.readouterr().out
    assert "Embedded 128/130 changed texts" in out and "Embedded 130/130 changed texts" in out
    assert len(active()[1]) == 130
