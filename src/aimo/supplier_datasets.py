"""Explicit operator import of Valio's static CSV evidence; never price/stock or authority.

Both snapshots are validated before one atomic publication. Catalog refreshes do not
erase these independent product-ID joins. Raw files remain outside source control.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aimo.db import connection
from aimo.ingest import CatalogError, download

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000
IMPORT_LOCK = 893020
TABLES = ("supplier_dataset_imports", "supplier_dataset_values", "active_supplier_datasets")


@dataclass(frozen=True)
class Dataset:
    name: str
    column: str
    sha256: str
    row_count: int

    @property
    def endpoint(self):
        return f"/api/{self.name.replace('_', '-')}/download"

    @property
    def filename(self):
        return self.name.replace("_", "-") + ".csv"


RELIABILITY = Dataset(
    "delivery_reliability",
    "deliveryReliability",
    "d24dc9e17d2652e7c21ea39fcf08e55522d044313031af1d9f3424fb84b2bb72",
    4425,
)
CARBON = Dataset(
    "carbon_footprint",
    "AVG kg CO2-eq/kg",
    "72b1ed6a22a0a40dcb7969d0c1f21229cdb5b64b5dba68b7db7fc7e947376eac",
    11033,
)


def read_snapshot(path: Path, dataset: Dataset):
    """Return exact decimals/unknowns. Never infer missing values or repair invalid rows."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CatalogError("DATASET_TOO_LARGE", "Supplier CSV exceeds the size limit")
    if not re.fullmatch(r"[0-9a-f]{64}", dataset.sha256) or (
        hashlib.sha256(raw).hexdigest() != dataset.sha256
    ):
        raise CatalogError("DATASET_HASH_MISMATCH", "Supplier CSV is not the approved snapshot")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if reader.fieldnames is None or sorted(reader.fieldnames) != sorted(
            ["productId", dataset.column]
        ):
            raise ValueError()
        rows, seen = [], set()
        for row in reader:
            pid = row["productId"]
            if (
                len(row) != 2
                or not isinstance(pid, str)
                or not re.fullmatch(r"[0-9]{1,32}", pid)
                or pid in seen
                or row[dataset.column] is None
                or len(rows) >= MAX_ROWS
            ):
                raise ValueError()
            seen.add(pid)
            text = row[dataset.column].strip()
            value = Decimal(text) if text else None
            if value is not None and (
                not value.is_finite()
                or value < 0
                or (dataset.name == RELIABILITY.name and value > 1)
            ):
                raise ValueError()
            rows.append((pid, value))
        if not rows or len(rows) != dataset.row_count:
            raise ValueError()
    except (UnicodeError, csv.Error, ValueError, InvalidOperation, KeyError):
        raise CatalogError(
            "DATASET_INVALID", "Supplier CSV has invalid headers, IDs, values or row count"
        ) from None
    return rows


def import_datasets(directory: Path, *, fetch=False, datasets=(RELIABILITY, CARBON)):
    """Schema-owner command. No application deployment, embeddings or catalog activation."""
    if tuple(d.name for d in datasets) != (RELIABILITY.name, CARBON.name):
        raise ValueError("Both supplier datasets are required in reliability/carbon order")
    directory.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for dataset in datasets:
        path = directory / dataset.filename
        if fetch:
            download(path, endpoint=dataset.endpoint)
        snapshots.append((dataset, read_snapshot(path, dataset)))
    result = {}
    with connection() as c:
        c.execute("SET LOCAL lock_timeout = '10s'")
        c.execute("SET LOCAL statement_timeout = '60s'")
        c.execute("SELECT pg_advisory_xact_lock(%s)", (IMPORT_LOCK,))
        for dataset, rows in snapshots:
            key = (dataset.name, dataset.sha256)
            inserted = c.execute(
                "INSERT INTO supplier_dataset_imports(dataset,sha256,source,row_count) "
                "VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING sha256",
                (*key, "https://junction26.valioaimo.fi" + dataset.endpoint, len(rows)),
            ).fetchone()
            if inserted:
                with c.cursor().copy(
                    "COPY supplier_dataset_values(dataset,sha256,product_id,value) FROM STDIN"
                ) as copy:
                    for pid, value in rows:
                        copy.write_row((*key, pid, value))
            count = c.execute(
                "SELECT count(*) AS n FROM supplier_dataset_values WHERE dataset=%s AND sha256=%s",
                key,
            ).fetchone()["n"]
            if count != len(rows):
                raise CatalogError("DATASET_INCOMPLETE", "Stored supplier snapshot is incomplete")
            c.execute(
                "INSERT INTO active_supplier_datasets(dataset,sha256) VALUES(%s,%s) "
                "ON CONFLICT(dataset) DO UPDATE SET sha256=excluded.sha256",
                key,
            )
            matched = c.execute(
                "SELECT count(*) AS n FROM supplier_dataset_values v "
                "JOIN active_catalog a ON true "
                "JOIN products p ON p.generation=a.generation AND p.id=v.product_id "
                "WHERE v.dataset=%s AND v.sha256=%s",
                key,
            ).fetchone()["n"]
            result[dataset.name] = {
                "sha256": dataset.sha256,
                "rows": count,
                "known_values": sum(value is not None for _, value in rows),
                "matched_catalog_products": matched,
                "status": "imported" if inserted else "already_imported",
            }
    return result
