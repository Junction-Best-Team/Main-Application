"""Verify golden cases against a private local snapshot without publishing raw records."""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from aimo.catalog import normalize, quantity
from aimo.ingest import CATALOG_SHA256

parser = argparse.ArgumentParser()
parser.add_argument("snapshot", type=Path)
args = parser.parse_args()

content = args.snapshot.read_bytes()
assert hashlib.sha256(content).hexdigest() == CATALOG_SHA256
wanted = {"464306", "465039", "460123", "460675", "460035", "468044", "469429"}
rows = {
    r["id"]: normalize(r, "verified-local-snapshot")
    for r in json.loads(content, parse_float=Decimal)
    if r["id"] in wanted
}
assert Decimal(quantity(rows["464306"], Decimal(1000), "L", True)["sales_quantity"]) == 1000
assert rows["465039"]["units"]["KI"] == "5.0"
assert quantity(rows["465039"], Decimal(1000), "L", True)["sales_quantity"] is None
assert Decimal(quantity(rows["460675"], Decimal(12), "KG", True)["sales_quantity"]) == 20
assert rows["460675"]["variable_weight"] is True
assert Decimal(quantity(rows["460035"], Decimal(4), "KG", True)["sales_quantity"]) == 6
assert rows["460035"]["variable_weight"] is True
assert (
    rows["468044"]["allergens"]["AM"] == "CONTAINS" and "AM" in rows["468044"]["allergen_conflicts"]
)
assert rows["469429"]["allergens"]["AM"] == "MAY_CONTAIN" and set(
    rows["469429"]["allergen_conflicts"]
) == {"AM", "AN"}
assert Decimal(rows["460123"]["units"]["KI"]) == 12
assert sum(Decimal(d["quantity"]) for d in rows["460123"]["deposits"]) * 10 == 120
print(
    json.dumps(
        {
            "snapshot_sha256": CATALOG_SHA256,
            "golden_products_verified": len(rows),
            "lettuce_also_variable_weight": True,
            "raw_records_exported": False,
        }
    )
)
