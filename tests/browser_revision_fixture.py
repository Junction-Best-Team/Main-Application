"""Create only this browser test's purchase, using the same DB as the fixture-mode app."""

import json
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from dotenv import load_dotenv

from aimo import conversations
from aimo.auth import internal_agent
from aimo.config import settings
from aimo.db import connection
from aimo.schemas import CommitRequest, PrepareRequest
from aimo.service import Service
from aimo.upstream import FixtureClient


def main():
    load_dotenv()
    if settings().upstream_mode != "fixture":
        raise RuntimeError("Historical approval browser setup requires fixture commerce.")
    with connection() as c:
        buyer = c.execute("SELECT * FROM identities WHERE id='buyer'").fetchone()
    agent = internal_agent(buyer)
    connector = FixtureClient()
    service = Service(connector)
    proposal = service.prepare_order(
        agent,
        PrepareRequest(
            idempotency_key=str(uuid4()),
            request_id=f"Historical terms regression {uuid4()}",
            destination="hotel-helsinki",
            delivery_date=date.today() + timedelta(days=2),
            lines=[
                {"product_id": "464306", "amount": "600", "unit": "L"},
                {"product_id": "464398", "amount": "400", "unit": "L", "substitutes_for": "464306"},
            ],
        ),
    )
    connector.price_multiplier = Decimal("1.10")
    revised = conversations.confirm(
        buyer,
        proposal["proposal_id"],
        CommitRequest(
            proposal_id=proposal["proposal_id"], revision=1, idempotency_key=str(uuid4())
        ),
        service,
    )
    conversations.confirm(
        buyer,
        revised["proposal_id"],
        CommitRequest(
            proposal_id=proposal["proposal_id"], revision=2, idempotency_key=str(uuid4())
        ),
        service,
    )
    print(
        json.dumps({"approval_id": proposal["approval_id"], "proposal_id": proposal["proposal_id"]})
    )


if __name__ == "__main__":
    main()
