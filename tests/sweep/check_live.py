"""Read-only live price/availability probe; no LLM, proposal or order is created."""

import argparse
import sys
from datetime import date, timedelta

from aimo.auth import internal_agent
from aimo.config import settings
from aimo.db import Problem, connection, now
from aimo.schemas import LookupRequest
from aimo.service import Service
from aimo.upstream import HELSINKI, ValioClient


def check_live(product_id, delivery_date, buyer_id="buyer"):
    if not settings().valio_aimo_api_key:
        raise Problem("UPSTREAM_CREDENTIALS_MISSING", "VALIO_AIMO_API_KEY is required.", 503)
    with connection() as c:
        buyer = c.execute(
            "SELECT * FROM identities WHERE id=%s AND role='approver' AND active", (buyer_id,)
        ).fetchone()
    if not buyer:
        raise Problem("BUYER_NOT_FOUND", "Configure an active buyer before the live probe.", 404)
    actor = internal_agent(buyer)
    service = Service(ValioClient())  # Explicitly live, regardless of auto/fixture configuration.
    service.get_product(actor, product_id)
    result = service.check_price_and_availability(
        actor, LookupRequest(product_ids=[product_id], delivery_date=delivery_date)
    )
    evidence = result["products"][product_id]
    reasons = sorted({reason["code"] for reason in evidence["reasons"]})
    if reasons:
        raise Problem("LIVE_EVIDENCE_UNRESOLVED", ", ".join(reasons), 502)
    return (
        f"PASS live supplier price and availability validated for {product_id} on {delivery_date}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", default="463380")
    parser.add_argument("--buyer", default="buyer")
    parser.add_argument(
        "--delivery-date",
        type=date.fromisoformat,
        default=now().astimezone(HELSINKI).date() + timedelta(days=2),
    )
    args = parser.parse_args()
    try:
        print(check_live(args.product, args.delivery_date, args.buyer))
    except Problem as exc:
        sys.exit(f"FAIL live supplier check: {exc.code}: {exc.message}")


if __name__ == "__main__":
    main()
