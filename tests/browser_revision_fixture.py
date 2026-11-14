"""Create only this browser test's purchase, using the same DB as the fixture-mode app."""

import json
import os
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from dotenv import load_dotenv

from aimo import approval_workflow as workflow
from aimo.auth import agent_identity
from aimo.config import settings
from aimo.db import connection
from aimo.schemas import CommitRequest, DecisionRequest, PurchaseRequest
from aimo.service import Service
from aimo.upstream import FixtureClient


def main():
    load_dotenv()
    if settings().upstream_mode != "fixture":
        raise RuntimeError("Historical approval browser setup requires fixture commerce.")
    agent = agent_identity("Bearer " + os.environ["DEMO_AGENT_TOKEN"])
    with connection() as c:
        buyer = c.execute("SELECT * FROM identities WHERE id='buyer'").fetchone()
    connector = FixtureClient()
    service = Service(connector)
    proposal = service.prepare_order(
        agent,
        PurchaseRequest(
            request_id=f"Historical terms regression {uuid4()}",
            destination="hotel-helsinki",
            delivery_date=date.today() + timedelta(days=2),
            lines=[
                {"product_id": "464306", "amount": "600", "unit": "L"},
                {"product_id": "464398", "amount": "400", "unit": "L", "substitutes_for": "464306"},
            ],
        ),
    )
    workflow.record_human_decision(
        buyer, proposal["approval_id"], DecisionRequest(revision=1, decision="approve")
    )
    connector.price_multiplier = Decimal("1.10")
    revised = service.commit_order(
        agent,
        CommitRequest(
            proposal_id=proposal["proposal_id"],
            revision=1,
            idempotency_key=str(uuid4()),
        ),
    )
    workflow.record_human_decision(
        buyer, revised["approval_id"], DecisionRequest(revision=2, decision="approve")
    )
    service.commit_order(
        agent,
        CommitRequest(
            proposal_id=proposal["proposal_id"],
            revision=2,
            idempotency_key=str(uuid4()),
        ),
    )
    print(
        json.dumps({"approval_id": proposal["approval_id"], "proposal_id": proposal["proposal_id"]})
    )


if __name__ == "__main__":
    main()
