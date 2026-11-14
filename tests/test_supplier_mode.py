"""JNP3-SUP-006: every supplier result records whether it came from the live API or from fixtures.

Fixture commerce only; no live call is made. `LiveLabelled` reuses the invented fixture responses but
reports `mode = "live"`, which exercises the label plumbing without touching the supplier.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from aimo.db import connection
from aimo.schemas import CommitRequest, LookupRequest, PrepareRequest
from aimo.service import Service
from aimo.upstream import FixtureClient


class LiveLabelled(FixtureClient):
    """Test double: invented data carrying the live label. Never a real supplier response."""

    mode = "live"


def stored_snapshot(proposal_id, revision=1):
    with connection() as c:
        return c.execute(
            "SELECT snapshot FROM proposal_revisions WHERE proposal_id=%s AND revision=%s",
            (proposal_id, revision),
        ).fetchone()["snapshot"]


@pytest.mark.parametrize(
    "connector_type,expected", [(FixtureClient, "fixture"), (LiveLabelled, "live")]
)
def test_lookup_result_and_every_product_carry_the_mode(agent, connector_type, expected):
    service = Service(connector_type())
    result = service.check_price_and_availability(
        agent,
        LookupRequest(
            product_ids=["464306", "464398"], delivery_date=date.today() + timedelta(days=2)
        ),
    )
    assert result["mode"] == expected
    assert set(result["products"]) == {"464306", "464398"}
    assert {p["mode"] for p in result["products"].values()} == {expected}


@pytest.mark.parametrize(
    "connector_type,expected", [(FixtureClient, "fixture"), (LiveLabelled, "live")]
)
def test_stored_proposal_and_receipt_record_the_mode(
    agent, request_data, connector_type, expected, confirm_terms
):
    service = Service(connector_type())
    proposal = service.prepare_order(agent, PrepareRequest(**request_data))
    assert proposal["policy_outcome"] == "ready_to_commit"
    assert proposal["snapshot"]["mode"] == expected

    # The record in the database, not only the response, carries the label.
    stored = stored_snapshot(proposal["proposal_id"])
    assert stored["mode"] == expected
    assert stored["lines"] and all(
        line["commercial_evidence"]["mode"] == expected for line in stored["lines"]
    )

    confirm_terms(proposal)  # every agent role needs a recorded customer confirmation (WS-D)
    receipt = service.commit_order(
        agent,
        CommitRequest(
            proposal_id=proposal["proposal_id"],
            revision=proposal["revision"],
            idempotency_key=str(uuid4()),
        ),
    )
    assert receipt["evidence_mode"] == expected
    assert service.get_order(agent, receipt["order_id"])["evidence_mode"] == expected


def test_a_mode_change_creates_a_new_revision_instead_of_reusing_old_terms(agent, request_data):
    """The mode is part of the material fingerprint, so fixture terms cannot be committed as live."""
    fixture_service = Service(FixtureClient())
    proposal = fixture_service.prepare_order(agent, PrepareRequest(**request_data))
    committed = Service(LiveLabelled()).commit_order(
        agent,
        CommitRequest(
            proposal_id=proposal["proposal_id"],
            revision=proposal["revision"],
            idempotency_key=str(uuid4()),
        ),
    )
    assert committed["status"] == "revised"
    assert committed["revision"] == proposal["revision"] + 1
    assert committed["snapshot"]["mode"] == "live"
