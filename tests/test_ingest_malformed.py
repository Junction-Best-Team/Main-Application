"""JNP3-SUP-002: a malformed catalog record is a clean, named error, not a KeyError.

The download is a supplier response too, so each record is checked and a bad one is reported by
position and id before anything is published. Synthetic snapshots only; the shared fixture catalog is
restored afterwards.
"""

import hashlib
import json
from copy import deepcopy

import pytest

from aimo.db import connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import ingest_file, publish


@pytest.fixture(autouse=True)
def restore_fixture_catalog():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


def good(pid):
    return {
        "id": pid,
        "salesUnit": "ST",
        "baseUnit": "ST",
        "allowedLotSize": "1",
        "units": [{"unitId": "ST", "sizeInBaseUnits": 1}],
        "synkkaData": {
            "names": [{"language": "en", "value": "Synthetic oat drink 1 l"}],
            "variableUnit": False,
            "classifications": [
                {"name": "allergen", "values": [{"id": "AM", "unit": "CONTAINS"}]},
            ],
            "unitConversions": [
                {
                    "synkkaPackagingType": "BASE_UNIT_OR_EACH",
                    "volume": {"unit": "LTR", "value": 1},
                }
            ],
        },
    }


def broken(mutate):
    record = deepcopy(good("920002"))
    mutate(record)
    return record


def drop(key):
    return lambda r: r.pop(key)


CASES = {
    "missing id": (lambda r: r.pop("id"), "#1", None),
    "non-string id": (lambda r: r.update(id=920002), "#1", None),
    "empty id": (lambda r: r.update(id=""), "#1", None),
    "unit without id": (lambda r: r["units"].append({"sizeInBaseUnits": 2}), "#1", "920002"),
    "unit without size": (lambda r: r["units"].append({"unitId": "KI"}), "#1", "920002"),
    "non-numeric size": (
        lambda r: r["units"].append({"unitId": "KI", "sizeInBaseUnits": "many"}),
        "#1",
        "920002",
    ),
    "units not a list": (lambda r: r.update(units=5), "#1", "920002"),
    "name without language": (
        lambda r: r["synkkaData"]["names"].append({"value": "x"}),
        "#1",
        "920002",
    ),
    "classification without name": (
        lambda r: r["synkkaData"]["classifications"].append({"values": []}),
        "#1",
        "920002",
    ),
    "classification value without id": (
        lambda r: r["synkkaData"]["classifications"][0]["values"].append({"unit": "CONTAINS"}),
        "#1",
        "920002",
    ),
    "non-numeric measurement": (
        lambda r: r["synkkaData"]["unitConversions"][0]["volume"].update(value="lots"),
        "#1",
        "920002",
    ),
    "non-numeric lot size": (lambda r: r.update(allowedLotSize="abc"), "#1", "920002"),
    "negative lot size": (lambda r: r.update(allowedLotSize="-1"), "#1", "920002"),
    "synkka data not an object": (lambda r: r.update(synkkaData=[1]), "#1", "920002"),
}


def snapshot(tmp_path, middle):
    records = [good("920001"), middle, good("920003")]
    path = tmp_path / "snapshot.json"
    content = json.dumps(records).encode()
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def active():
    with connection() as c:
        return str(c.execute("SELECT generation FROM active_catalog").fetchone()["generation"])


def test_control_a_well_formed_snapshot_is_published(tmp_path):
    path, sha = snapshot(tmp_path, good("920002"))
    result = ingest_file(path, expected_count=3, expected_sha=sha, carry_withdrawn=False)
    assert result["products"] == 3 and result["active"] is True


@pytest.mark.parametrize("name", CASES)
def test_a_malformed_record_is_a_clean_error_naming_the_record(tmp_path, name):
    mutate, position, pid = CASES[name]
    path, sha = snapshot(tmp_path, broken(mutate))
    before = active()
    with pytest.raises(ValueError) as error:  # KeyError and friends are not ValueError
        ingest_file(path, expected_count=3, expected_sha=sha)
    message = str(error.value)
    assert "record" in message.lower() and position in message
    if pid:
        assert pid in message
    assert active() == before  # nothing was published


@pytest.mark.parametrize("bad", [None, 7, "text", ["list"]])
def test_a_record_that_is_not_an_object_is_a_clean_error(tmp_path, bad):
    path, sha = snapshot(tmp_path, bad)
    with pytest.raises(ValueError, match="#1"):
        ingest_file(path, expected_count=3, expected_sha=sha)
