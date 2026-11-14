"""JNP3-DIS-008 and JNP3-DIS-009 (Draft): a product absent from a newer snapshot.

DIS-008: the ingestion command keeps a product absent from a newer snapshot as a withdrawn product
that exact lookup still returns. DIS-009: the tools backend never offers a withdrawn product as a
candidate (the flagged-withdrawn case is covered by tests/test_search_contract.py; this file covers
the ABSENT case, which only exists once DIS-008 is built, plus text queries).

Synthetic snapshots through the real ingest_file with fixture embeddings; the shared fixture
catalog is restored after each test. Nothing here is built yet, so each test is a strict xfail.
"""

import hashlib
import json
from datetime import date, timedelta
from uuid import uuid4

import pytest

from aimo.db import Problem, connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import ingest_file, publish
from aimo.schemas import PrepareRequest, SearchRequest
from aimo.search import get_product, search_products

GONE = "wa-90003"
GONE_GTIN = "6430009900033"
STRATEGIES = ("keyword", "semantic", "hybrid")


@pytest.fixture(autouse=True)
def restore_fixture_catalog():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


def raw_product(pid, name, gtin=None, **extra):
    return {
        "id": pid,
        "salesUnit": "ST",
        "baseUnit": "ST",
        "allowedLotSize": "1",
        "units": [{"unitId": "ST", "sizeInBaseUnits": 1}],
        "salesUnitGtin": gtin,
        "synkkaData": {
            "names": [{"language": "en", "value": name}],
            "variableUnit": False,
            "classifications": [],
            "unitConversions": [],
        },
        **extra,
    }


def snapshot_a():
    # Enough live filler that fixture products carried forward as withdrawn stay a small share and
    # the 10 percent rule (DIS-012) does not trim the product under test.
    filler = [raw_product(f"wa-fill-{i:02d}", f"Withdrawal filler {i:02d}") for i in range(60)]
    return [
        raw_product("wa-90001", "Withdrawal test oat drink"),
        raw_product("wa-90002", "Withdrawal test cream"),
        raw_product(GONE, "Withdrawal zebramilk special", GONE_GTIN),
        *filler,
    ]


def snapshot_b():
    return [p for p in snapshot_a() if p["id"] != GONE]  # dropped; nothing says it was deleted


def ingest(tmp_path, name, records):
    path = tmp_path / f"{name}.json"
    content = json.dumps(records).encode()
    path.write_bytes(content)
    return ingest_file(path, len(records), hashlib.sha256(content).hexdigest())


def generation_ids(generation):
    """The synthetic ids of a generation. Fixture products that were active before the first
    snapshot are carried forward as withdrawn (DIS-008) and are ignored here."""
    with connection() as c:
        return {
            r["id"]
            for r in c.execute("SELECT id FROM products WHERE generation=%s", (generation,))
            if r["id"].startswith("wa-9")
        }


def prepare(service, agent, product_id):
    request = PrepareRequest.model_validate(
        {
            "request_id": "Withdrawal check",
            "idempotency_key": str(uuid4()),
            "destination": "hotel-helsinki",
            "delivery_date": str(date.today() + timedelta(days=2)),
            "requirements": {},
            "lines": [{"product_id": product_id, "amount": "2", "unit": "ST"}],
        }
    )
    return service.prepare_order(agent, request)


def reason_codes(proposal):
    return {r["code"] for r in proposal["reasons"]}


def test_control_two_snapshots_published_and_a_flagged_product_is_denied_as_withdrawn(
    tmp_path, service, agent
):
    """Control (passes today): snapshot A holds three products, snapshot B two; the older
    generation is retained, and a product *flagged* deleted is denied with PRODUCT_DELETED."""
    first = ingest(tmp_path, "a", snapshot_a())
    assert generation_ids(first["generation"]) == {"wa-90001", "wa-90002", GONE}
    second = ingest(tmp_path, "b", snapshot_b())
    assert second["generation"] != first["generation"]
    assert generation_ids(first["generation"]) >= {GONE}  # A is still retained for rollback
    assert {"wa-90001", "wa-90002"} <= generation_ids(second["generation"])
    ingest(tmp_path, "c", [*snapshot_b(), raw_product("wa-90004", "Flagged", deleted=True)])
    proposal = prepare(service, agent, "wa-90004")
    assert "PRODUCT_DELETED" in reason_codes(proposal) and proposal["policy_outcome"] == "denied"


def test_a_product_absent_from_the_newer_snapshot_is_kept_as_withdrawn(tmp_path, agent):
    """JNP3-DIS-008: after snapshot A then B (without GONE), get_product(GONE) returns the product
    with deleted True instead of NOT_FOUND, and the ingest result counts it as withdrawn."""
    first = ingest(tmp_path, "a", snapshot_a())
    result = ingest(tmp_path, "b", snapshot_b())
    try:
        product = get_product(agent, GONE)
    except Problem as error:
        pytest.fail(f"absent product is not retained as withdrawn: {error.code}")
    assert product["id"] == GONE and product["deleted"] is True
    # The result counts withdrawn products still stored (older fixture tombstones may be trimmed).
    assert result["withdrawn_products"] >= 1
    assert first["products"] > 0


def test_the_withdrawn_product_survives_later_snapshots_that_still_lack_it(tmp_path, agent):
    """JNP3-DIS-008: A, B (without GONE), then C (still without GONE, one new product): exact
    lookup of GONE still returns it as deleted True."""
    ingest(tmp_path, "a", snapshot_a())
    ingest(tmp_path, "b", snapshot_b())
    ingest(tmp_path, "c", [*snapshot_b(), raw_product("wa-90005", "Withdrawal newcomer")])
    try:
        product = get_product(agent, GONE)
    except Problem as error:
        pytest.fail(f"withdrawn product forgotten by a later snapshot: {error.code}")
    assert product["deleted"] is True


def test_an_order_for_an_absent_product_is_denied_as_withdrawn_not_unknown(
    tmp_path, service, agent
):
    """JNP3-DIS-008: prepare_order for GONE gives PRODUCT_DELETED and outcome denied, and does not
    give PRODUCT_UNKNOWN."""
    ingest(tmp_path, "a", snapshot_a())
    ingest(tmp_path, "b", snapshot_b())
    proposal = prepare(service, agent, GONE)
    codes = reason_codes(proposal)
    assert "PRODUCT_UNKNOWN" not in codes, codes
    assert "PRODUCT_DELETED" in codes, codes
    assert proposal["policy_outcome"] == "denied"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_product_withdrawn_by_absence_is_never_a_candidate(tmp_path, agent, strategy):
    """JNP3-DIS-009 (after DIS-008): GONE is retained as withdrawn, yet name, id and GTIN queries
    never return it as a candidate under any strategy, while its neighbours are still found."""
    ingest(tmp_path, "a", snapshot_a())
    ingest(tmp_path, "b", snapshot_b())
    try:
        assert get_product(agent, GONE)["deleted"] is True  # the product is stored, so the
    except Problem as error:  # exclusion below is real
        pytest.fail(f"absent product is not retained as withdrawn: {error.code}")
    for query in ("Withdrawal zebramilk special", "zebramilk", GONE, GONE_GTIN):
        result = search_products(agent, SearchRequest(query=query), strategy)
        assert GONE not in {p["id"] for p in result["products"]}, query
    control = search_products(agent, SearchRequest(query="Withdrawal test oat drink"), strategy)
    assert "wa-90001" in {p["id"] for p in control["products"]}
