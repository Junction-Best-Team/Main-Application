"""Read-only shortlist probe. Prints a compact evidence summary, never the credential/raw dataset."""

import argparse
import json
from datetime import date

from aimo.db import connection, now
from aimo.purchases import load_products
from aimo.upstream import ValioClient, validate_lookup

parser = argparse.ArgumentParser()
parser.add_argument("--date", type=date.fromisoformat, required=True)
parser.add_argument("--ids", nargs="+", default=["463380", "464306", "464398", "461893", "476230"])
args = parser.parse_args()
if not 1 <= len(args.ids) <= 20:
    parser.error("Probe accepts 1–20 IDs")
with connection() as c:
    buyer = c.execute("SELECT upstream_customer FROM buyers WHERE id='demo-hotel'").fetchone()
    products = load_products(c, args.ids)
raw = ValioClient().lookup(buyer["upstream_customer"], args.ids, args.date)
validated = validate_lookup(raw, buyer["upstream_customer"], args.ids, args.date, products, now())
print(
    json.dumps(
        {
            "observed_at": raw["observed_at"],
            "mode": "live",
            "requested_date": str(args.date),
            "products": [
                {k: v for k, v in item.items() if k not in ("source",)}
                for item in validated.values()
            ],
        },
        indent=2,
    )
)
