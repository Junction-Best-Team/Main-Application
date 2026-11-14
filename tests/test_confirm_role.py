"""JNP3-CNF-003: a customer confirmation comes from a human (approver) role, by role.

Before this check the refusal of an agent depended on a data value (its empty authority, Q-35).
Here the internal agent's identity row is given approver-like authority with privileged database
access (the test role owns the tables; the runtime role cannot write `identities`), and the
confirmation must still be refused by role. Probe: evidence/verify/ws-c.md CNF-003.
"""

from uuid import uuid4

import pytest

from aimo import auth, conversations
from aimo.db import Problem, connection, js
from aimo.schemas import CommitRequest, PrepareRequest

APPROVER_LIKE = {
    "currency": "EUR",
    "max_gross": "5000.00",
    "exceptions": ["substitution", "overbuy"],
}


def counts():
    with connection() as c:
        return (
            c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"],
            c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"],
        )


def test_an_agent_with_approver_like_authority_cannot_confirm(service, buyer, request_data):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    with connection() as c:
        c.execute(
            "UPDATE identities SET authority=%s WHERE id=%s", (js(APPROVER_LIKE), internal["id"])
        )
    agent = auth.internal_agent(buyer)
    assert agent["authority"] == APPROVER_LIKE and agent["role"] == "agent"
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    with pytest.raises(Problem) as refused:
        conversations.confirm(agent, p["proposal_id"], body, service)
    assert (refused.value.code, refused.value.status) == ("FORBIDDEN", 403)
    assert counts() == (0, 0)


def test_the_buyer_can_still_confirm(service, buyer, request_data):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    assert (
        conversations.confirm(buyer, p["proposal_id"], body, service)["status"] == "accepted_mock"
    )
    assert counts() == (1, 1)
