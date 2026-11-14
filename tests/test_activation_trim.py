"""JNP3-DIS-012 on the staged path: `aimo ingest --stage` then `aimo activate-catalog`.

`publish` trims withdrawn products past 10 percent when it activates, but a staged generation is
published inactive, so activating it later must trim too (hotfix: before, 18 of 70 stayed withdrawn
and the next sync said `unchanged`). Protected products (named by a pending proposal) are kept.
"""

import hashlib
import json

import pytest
from test_catalog_sync import sync
from test_ingest import raw_product

from aimo.db import connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import activate_catalog, ingest_file, publish
from aimo.schemas import PrepareRequest


@pytest.fixture(autouse=True)
def restore_fixture_catalog():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


def snapshot(tmp_path, withdrawn_ids, live=52):
    records = [raw_product(f"act-{i:02d}", f"Activation item {i:02d}") for i in range(live)]
    records += [raw_product(pid, f"Withdrawn {pid}", deleted=True) for pid in withdrawn_ids]
    path = tmp_path / "snapshot.json"
    content = json.dumps(records).encode()
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest(), len(records)


def rows(generation):
    with connection() as c:
        stored = c.execute(
            "SELECT id, COALESCE((facts->>'deleted')::boolean,false) AS deleted FROM products "
            "WHERE generation=%s",
            (generation,),
        ).fetchall()
        count = c.execute(
            "SELECT product_count FROM catalog_generations WHERE id=%s", (generation,)
        ).fetchone()["product_count"]
    return {r["id"]: r["deleted"] for r in stored}, count


def test_activating_a_staged_generation_trims_withdrawn_products_past_ten_percent(tmp_path):
    withdrawn = [f"wd-{i:02d}" for i in range(18)]
    path, sha, count = snapshot(tmp_path, withdrawn)
    assert count == 70
    staged = ingest_file(path, count, sha, activate=False, carry_withdrawn=False)
    stored, _ = rows(staged["generation"])
    assert len(stored) == 70 and sum(stored.values()) == 18  # 25.7 percent withdrawn, staged
    result = activate_catalog(staged["generation"])
    stored, product_count = rows(staged["generation"])
    assert result["trimmed_withdrawn"] == 70 - len(stored) > 0
    assert sum(stored.values()) / len(stored) <= 0.10
    assert product_count == len(stored)  # the generation stays re-activatable
    assert result["products"] == len(stored)
    assert sum(1 for deleted in stored.values() if not deleted) == 52  # live products untouched


def test_activation_keeps_a_withdrawn_product_a_pending_proposal_names(
    tmp_path, service, agent, request_data
):
    pending = service.prepare_order(agent, PrepareRequest(**request_data))  # names 464306
    assert pending["order_id"] is None
    withdrawn = ["464306"] + [f"wd-{i:02d}" for i in range(17)]
    path, sha, count = snapshot(tmp_path, withdrawn)
    staged = ingest_file(path, count, sha, activate=False, carry_withdrawn=False)
    activate_catalog(staged["generation"])
    stored, _ = rows(staged["generation"])
    assert stored["464306"] is True  # protected by the pending proposal, though withdrawn
    others = [pid for pid, deleted in stored.items() if deleted and pid != "464306"]
    assert len(others) < 17  # unprotected ones were trimmed


def test_the_next_sync_after_a_staged_activation_is_unchanged(tmp_path):
    with connection() as c:
        c.execute("DELETE FROM active_catalog")
    path, sha, count = snapshot(tmp_path, [f"wd-{i:02d}" for i in range(18)])
    staged = ingest_file(path, count, sha, activate=False, carry_withdrawn=False)
    activate_catalog(staged["generation"])
    stored, _ = rows(staged["generation"])
    assert sum(stored.values()) / len(stored) <= 0.10  # trimmed on activation
    again = sync(path, sha, count)
    assert again["outcome"] == "unchanged" and again["generation"] == staged["generation"]


def test_activation_without_withdrawn_products_trims_nothing_and_a_retry_is_safe(tmp_path):
    path, sha, count = snapshot(tmp_path, [], live=30)
    staged = ingest_file(path, count, sha, activate=False, carry_withdrawn=False)
    first = activate_catalog(staged["generation"])
    second = activate_catalog(staged["generation"])  # idempotent
    assert first["trimmed_withdrawn"] == second["trimmed_withdrawn"] == 0
    assert first["products"] == second["products"] == 30
