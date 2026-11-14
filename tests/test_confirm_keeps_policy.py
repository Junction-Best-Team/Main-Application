"""JNP3-POL-005: confirming a recipe/basket never changes the standing approved product list."""

from uuid import uuid4

import pytest

from aimo import auth, conversations
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, PrepareRequest


def policy_state():
    with connection() as c:
        buyer = c.execute("SELECT * FROM buyers WHERE id='demo-hotel'").fetchone()
        rows = c.execute(
            "SELECT * FROM policies WHERE buyer_id='demo-hotel' ORDER BY version"
        ).fetchall()
    return buyer["current_policy"], rows


def body(p, revision=1):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=revision, idempotency_key=str(uuid4())
    )


def test_confirm_replay_and_refusal_leave_policy_rows_untouched(service, buyer, request_data):
    before = policy_state()
    assert before[1][0]["rules"]["approved_product_ids"] == ["464306"]
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    first = body(p)
    receipt = conversations.confirm(buyer, p["proposal_id"], first, service)
    assert receipt["status"] == "accepted_mock"
    assert conversations.confirm(buyer, p["proposal_id"], first, service) == receipt  # replay
    with pytest.raises(Problem):  # a second confirmation of a finalized purchase is refused
        conversations.confirm(buyer, p["proposal_id"], body(p), service)
    assert policy_state() == before


def test_confirming_an_outside_scope_basket_does_not_add_the_product_to_the_list(
    service, buyer, request_data
):
    before = policy_state()
    request_data["lines"] = [{"product_id": "464398", "amount": "10", "unit": "L"}]
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "approval_required"
    receipt = conversations.confirm(buyer, p["proposal_id"], body(p), service)
    assert receipt["status"] == "accepted_mock"
    version, rows = policy_state()
    assert (version, rows) == before
    assert rows[-1]["rules"]["approved_product_ids"] == ["464306"]
    assert "464398" not in rows[-1]["rules"]["approved_product_ids"]


def test_blocked_confirmation_leaves_policy_rows_untouched(service, buyer, request_data):
    before = policy_state()
    request_data["budget_gross"] = "1"  # denied: hard budget
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "denied"
    with pytest.raises(Problem) as error:
        conversations.confirm(buyer, p["proposal_id"], body(p), service)
    assert error.value.code == "COMMIT_BLOCKED"
    assert policy_state() == before
