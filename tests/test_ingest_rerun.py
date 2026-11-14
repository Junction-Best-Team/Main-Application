"""JNP3-DIS-002: `aimo ingest` publishes a complete snapshot as a new catalog generation and makes it
active; a rerun is safe and a failed run changes nothing.

These tests drive the real command (`aimo.cli.main`) into the real test database with synthetic
snapshots and fixture embeddings. The shared fixture catalog is restored after each test.
"""

import hashlib
import json
import sys

import pytest

import aimo.cli as cli
from aimo.db import connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import activate_catalog, publish


@pytest.fixture(autouse=True)
def restore_fixture_catalog():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


def raw_product(pid, name):
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
            "unitConversions": [],
        },
    }


def snapshot(tmp_path, name, records):
    path = tmp_path / f"{name}.json"
    content = json.dumps(records).encode()
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def ingest_command(monkeypatch, capsys, path, sha, count):
    monkeypatch.setattr(
        sys,
        "argv",
        ["aimo", "ingest", "--file", str(path), "--expected-count", str(count)]
        + ["--expected-sha256", sha],
    )
    cli.main()
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def active_generation():
    with connection() as c:
        row = c.execute("SELECT generation FROM active_catalog").fetchone()
        ids = {
            r["id"]
            for r in c.execute("SELECT id FROM products WHERE generation=%s", (row["generation"],))
        }
    return str(row["generation"]), ids


def test_command_publishes_the_whole_snapshot_as_the_active_generation(
    monkeypatch, capsys, tmp_path
):
    records = [raw_product("910001", "Rerun test oat drink"), raw_product("910002", "Rerun cream")]
    path, sha = snapshot(tmp_path, "one", records)
    result = ingest_command(monkeypatch, capsys, path, sha, 2)
    generation, ids = active_generation()
    assert result["active"] is True and result["generation"] == generation
    assert ids == {"910001", "910002"}  # exactly the snapshot, nothing carried over from before


def test_rerunning_an_unchanged_snapshot_is_safe_and_reuses_embeddings(
    monkeypatch, capsys, tmp_path
):
    records = [raw_product("910001", "Rerun test oat drink"), raw_product("910002", "Rerun cream")]
    path, sha = snapshot(tmp_path, "same", records)
    first = ingest_command(monkeypatch, capsys, path, sha, 2)
    _, ids_before = active_generation()
    second = ingest_command(monkeypatch, capsys, path, sha, 2)
    generation, ids_after = active_generation()
    assert second["generation"] != first["generation"]  # a new generation, not row updates
    assert generation == second["generation"]
    assert ids_after == ids_before == {"910001", "910002"}
    assert second["new_embeddings"] == 0 and second["reused_embeddings"] == 2
    with connection() as c:
        total = c.execute(
            "SELECT count(*) AS n FROM products WHERE generation=%s", (generation,)
        ).fetchone()["n"]
        stored = c.execute(
            "SELECT product_count FROM catalog_generations WHERE id=%s", (generation,)
        ).fetchone()["product_count"]
    assert total == stored == 2  # no duplicate or partial rows


def test_a_refused_run_leaves_the_active_catalog_untouched(monkeypatch, capsys, tmp_path):
    good, good_sha = snapshot(tmp_path, "good", [raw_product("910001", "Rerun test oat drink")])
    ingest_command(monkeypatch, capsys, good, good_sha, 1)
    before = active_generation()
    other, _ = snapshot(tmp_path, "other", [raw_product("910009", "Never published")])
    for count, sha in [(1, "0" * 64), (5, hashlib.sha256(other.read_bytes()).hexdigest())]:
        with pytest.raises(ValueError):
            ingest_command(monkeypatch, capsys, other, sha, count)
        assert active_generation() == before


def test_rerunning_the_same_snapshot_keeps_the_last_different_catalog_for_rollback(
    monkeypatch, capsys, tmp_path
):
    old_path, old_sha = snapshot(tmp_path, "old", [raw_product("910001", "Rerun old catalog")])
    new_path, new_sha = snapshot(
        tmp_path, "new", [raw_product("910001", "Rerun old catalog"), raw_product("910002", "New")]
    )
    old = ingest_command(monkeypatch, capsys, old_path, old_sha, 1)
    ingest_command(monkeypatch, capsys, new_path, new_sha, 2)
    ingest_command(monkeypatch, capsys, new_path, new_sha, 2)  # operator reruns the same snapshot
    with connection() as c:  # the identical older copy gave up its slot, not the different one
        kept = {r["id"] for r in c.execute("SELECT DISTINCT generation AS id FROM products")}
    assert old["generation"] in {str(g) for g in kept}
    activate_catalog(old["generation"])  # roll back to the earlier, different catalog
    assert active_generation()[1] == {"910001"}
