"""Authored CSVs only. No supplier calls, real dataset or hosted database."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import httpx
import psycopg
import pytest
from psycopg import sql

from aimo import ingest
from aimo.config import settings
from aimo.db import connection
from aimo.ingest import CatalogError
from aimo.permissions import configure_runtime_role
from aimo.supplier_datasets import CARBON, RELIABILITY, TABLES, import_datasets, read_snapshot


@pytest.fixture(autouse=True)
def isolated_datasets():
    with connection() as c:
        c.execute(
            "TRUNCATE active_supplier_datasets,supplier_dataset_values,supplier_dataset_imports"
        )
    yield
    with connection() as c:
        c.execute(
            "TRUNCATE active_supplier_datasets,supplier_dataset_values,supplier_dataset_imports"
        )


def snapshot(directory, dataset, body, count):
    raw = ("productId," + dataset.column + "\n" + body).encode()
    path = directory / dataset.filename
    path.write_bytes(raw)
    return replace(dataset, sha256=hashlib.sha256(raw).hexdigest(), row_count=count)


def pair(directory):
    return (
        snapshot(directory, RELIABILITY, "464306,0\n999999,\n", 2),
        snapshot(directory, CARBON, "464306,2.315\n", 1),
    )


def test_exact_values_zero_unknown_and_absent_ids_stay_distinct(tmp_path):
    datasets = pair(tmp_path)
    assert read_snapshot(tmp_path / datasets[0].filename, datasets[0]) == [
        ("464306", Decimal(0)),
        ("999999", None),
    ]
    before = None
    with connection() as c:
        before = c.execute("SELECT generation FROM active_catalog").fetchone()
    result = import_datasets(tmp_path, datasets=datasets)
    assert result[RELIABILITY.name]["known_values"] == 1
    assert result[RELIABILITY.name]["matched_catalog_products"] == 1
    with connection() as c:
        rows = c.execute(
            "SELECT product_id,value FROM supplier_dataset_values WHERE dataset=%s ORDER BY product_id",
            (RELIABILITY.name,),
        ).fetchall()
        assert rows == [
            {"product_id": "464306", "value": Decimal(0)},
            {"product_id": "999999", "value": None},
        ]
        assert c.execute("SELECT generation FROM active_catalog").fetchone() == before
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "body",
    [
        "464306,NaN\n",
        "464306,Infinity\n",
        "464306,-1\n",
        "464306,1.01\n",
        "464306,bad\n",
        "464306,1,extra\n",
        "464306\n",
        "unknown,1\n",
        "464306,1\n464306,0\n",
    ],
)
def test_invalid_reliability_is_rejected_without_rows(tmp_path, body):
    dataset = snapshot(tmp_path, RELIABILITY, body, 1)
    with pytest.raises(CatalogError, match="invalid"):
        read_snapshot(tmp_path / dataset.filename, dataset)


def test_hash_headers_row_count_and_size_are_verified(tmp_path, monkeypatch):
    dataset = snapshot(tmp_path, CARBON, "464306,1\n", 1)
    path = tmp_path / dataset.filename
    with pytest.raises(CatalogError, match="approved"):
        read_snapshot(path, replace(dataset, sha256="0" * 64))
    with pytest.raises(CatalogError, match="invalid"):
        read_snapshot(path, replace(dataset, row_count=2))
    with pytest.raises(CatalogError, match="invalid"):
        read_snapshot(path, replace(dataset, column="wrong"))
    monkeypatch.setattr("aimo.supplier_datasets.MAX_BYTES", 1)
    with pytest.raises(CatalogError, match="size limit"):
        read_snapshot(path, dataset)


def test_invalid_second_snapshot_preserves_previous_pair(tmp_path):
    original = pair(tmp_path)
    import_datasets(tmp_path, datasets=original)
    new = snapshot(tmp_path, RELIABILITY, "464306,0.5\n", 1)
    (tmp_path / CARBON.filename).write_text("corrupt")
    with pytest.raises(CatalogError):
        import_datasets(tmp_path, datasets=(new, original[1]))
    with connection() as c:
        assert {r["sha256"] for r in c.execute("SELECT sha256 FROM active_supplier_datasets")} == {
            d.sha256 for d in original
        }
        assert c.execute("SELECT count(*) AS n FROM supplier_dataset_imports").fetchone()["n"] == 2


def test_database_failure_during_second_import_rolls_back_first(tmp_path):
    datasets = pair(tmp_path)
    # A committed empty snapshot simulates externally damaged data. Publication must refuse it
    # and roll back the first dataset rather than exposing a half-updated pair.
    with connection() as c:
        c.execute(
            "INSERT INTO supplier_dataset_imports(dataset,sha256,source,row_count) VALUES(%s,%s,'test',1)",
            (CARBON.name, datasets[1].sha256),
        )
    with pytest.raises(CatalogError, match="incomplete"):
        import_datasets(tmp_path, datasets=datasets)
    with connection() as c:
        assert not c.execute("SELECT * FROM active_supplier_datasets").fetchall()
        assert not c.execute("SELECT * FROM supplier_dataset_values").fetchall()
        assert c.execute("SELECT count(*) AS n FROM supplier_dataset_imports").fetchone()["n"] == 1


def test_retries_and_concurrent_imports_keep_one_snapshot(tmp_path):
    datasets = pair(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = [executor.submit(import_datasets, tmp_path, datasets=datasets) for _ in range(2)]
        outcomes = [attempt.result(timeout=15) for attempt in attempts]
    assert sorted(r[CARBON.name]["status"] for r in outcomes) == ["already_imported", "imported"]
    with connection() as c:
        before = c.execute("SELECT * FROM supplier_dataset_imports ORDER BY dataset").fetchall()
    result = import_datasets(tmp_path, datasets=datasets)
    assert result[CARBON.name]["status"] == "already_imported"
    with connection() as c:
        assert (
            c.execute("SELECT * FROM supplier_dataset_imports ORDER BY dataset").fetchall()
            == before
        )
        assert c.execute("SELECT count(*) AS n FROM supplier_dataset_values").fetchone()["n"] == 3


@pytest.mark.parametrize("dataset", [RELIABILITY, CARBON])
def test_csv_download_uses_supplied_endpoint_and_strips_redirect_credentials(
    tmp_path, monkeypatch, dataset
):
    seen = []
    cfg = settings().model_copy(update={"valio_aimo_api_key": "authored-test-key"})
    monkeypatch.setattr(ingest, "settings", lambda: cfg)
    real = httpx.AsyncClient

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "https://files.test/data.csv"})
        return httpx.Response(200, content=b"authored csv")

    monkeypatch.setattr(
        ingest.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    ingest.download(tmp_path / "csv", endpoint=dataset.endpoint)
    assert seen[0].url.path == dataset.endpoint
    assert seen[0].headers["X-API-Key"] == "authored-test-key"
    assert "X-API-Key" not in seen[1].headers


def test_runtime_reads_but_cannot_edit_supplier_evidence():
    with psycopg.connect(settings().database_url) as c:
        try:
            c.execute("CREATE ROLE supplier_dataset_runtime_test NOLOGIN")
            configure_runtime_role(c, "supplier_dataset_runtime_test")
            c.execute("SET LOCAL ROLE supplier_dataset_runtime_test")
            for name in TABLES:
                assert (
                    c.execute(
                        sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))
                    ).fetchone()[0]
                    == 0
                )
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    assert not c.execute(
                        "SELECT has_table_privilege(current_user,%s,%s)", (name, privilege)
                    ).fetchone()[0]
        finally:
            c.rollback()
