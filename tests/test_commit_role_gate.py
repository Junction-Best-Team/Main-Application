"""JNP3-CNF-001/003/023: the commit gate dispatches on the identity role and fails closed.

The gate used to be `if role == "agent": ...`, so any other role skipped it like an approver
does. A role that the application does not know, and the future `scheduler` role (which may only
commit against a valid scheduled authorization, none of which exists yet), must be refused.
`identities.role` still allows only agent and approver, so the other roles are simulated by
substituting the role after the real identity lookup; nothing is written to `identities`.
"""

from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo import auth, purchases
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, PrepareRequest


def with_role(monkeypatch, real_identity, role):
    """An identity claiming `role`; every context() lookup still resolves the real row."""
    real_context = purchases.context
    substitute = lambda c, identity, lock=False: real_context(c, real_identity, lock)  # noqa: E731
    monkeypatch.setattr(workflow, "context", substitute)
    monkeypatch.setattr(purchases, "context", substitute)
    return real_identity | {"role": role}


def prepared(service, buyer, request_data):
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    assert p["policy_outcome"] == "ready_to_commit"
    return p


def commit_body(p):
    return CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))


def orders():
    with connection() as c:
        return c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]


@pytest.mark.parametrize(
    ("role", "code", "status"),
    [
        # The scheduler sees only proposals that belong to one of its runs, so a proposal that
        # belongs to none is not even found; the gate branch below it is tested in
        # test_scheduler_engine.py.
        ("scheduler", "NOT_FOUND", 404),
        ("janitor", "FORBIDDEN", 403),
    ],
)
def test_a_role_without_a_gate_branch_cannot_commit(
    role, code, status, service, buyer, request_data, monkeypatch
):
    p = prepared(service, buyer, request_data)
    identity = with_role(monkeypatch, auth.internal_agent(buyer), role)
    with pytest.raises(Problem) as refused:
        service.commit_order(identity, commit_body(p))
    assert (refused.value.code, refused.value.status) == (code, status)
    assert orders() == 0


def test_the_agent_still_needs_a_recorded_customer_confirmation(service, buyer, request_data):
    p = prepared(service, buyer, request_data)
    with pytest.raises(Problem) as refused:
        service.commit_order(auth.internal_agent(buyer), commit_body(p))
    assert refused.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"
    assert orders() == 0


def test_an_approver_identity_still_commits_through_the_service(service, buyer, request_data):
    p = prepared(service, buyer, request_data)
    assert service.commit_order(buyer, commit_body(p))["status"] == "accepted_mock"
    assert orders() == 1
