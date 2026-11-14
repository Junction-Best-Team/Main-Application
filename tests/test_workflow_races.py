"""Re-checks inside the locked commit/prepare transactions, and authority drift seen by readers.

The lookup between the unlocked and the locked transaction is where the world can change, so
these tests inject the change at that exact point (a wrapper around build_snapshot) and check the
commit is refused or revised rather than honoured on stale evidence.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo.db import Problem, connection, js, now
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest
from aimo.upstream import FixtureClient


def commit(p, key=None):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=key or str(uuid4())
    )


def decide(buyer, p, decision="approve"):
    return workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=p["revision"], decision=decision)
    )


def code_of(fn):
    with pytest.raises(Problem) as error:
        fn()
    return error.value.code


def after_lookup(monkeypatch, action):
    """Run `action` once, right after the commit's evidence lookup and before its locked re-check."""
    real = workflow.build_snapshot
    fired = []

    def wrapper(*args, **kwargs):
        result = real(*args, **kwargs)
        if not fired:
            fired.append(True)
            action()
        return result

    monkeypatch.setattr(workflow, "build_snapshot", wrapper)


def add_policy_version():
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id='demo-hotel' FOR UPDATE")
        rules = c.execute(
            "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
        ).fetchone()["rules"]
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)", (js(rules),)
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")


def test_prepare_refuses_when_the_policy_changes_during_lookup(
    monkeypatch, service, agent, request_data
):
    after_lookup(monkeypatch, add_policy_version)
    assert code_of(lambda: service.prepare_order(agent, PrepareRequest(**request_data))) == (
        "POLICY_CHANGED"
    )
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM proposals").fetchone()["n"] == 0


def test_commit_refuses_when_the_policy_changes_during_lookup(
    monkeypatch, service, agent, request_data
):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    after_lookup(monkeypatch, add_policy_version)
    assert code_of(lambda: service.commit_order(agent, commit(p))) == "POLICY_CHANGED"
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM orders").fetchone()["n"] == 0


def test_commit_refuses_when_another_caller_revised_during_lookup(
    monkeypatch, service, agent, request_data
):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    dearer = FixtureClient()
    dearer.price_multiplier = Decimal(2)
    revised = []
    after_lookup(
        monkeypatch,
        lambda: revised.append(workflow.commit_order(agent, commit(p), dearer)),
    )
    assert code_of(lambda: service.commit_order(agent, commit(p))) == "STALE_REVISION"
    assert revised[0]["status"] == "revised" and revised[0]["revision"] == 2
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM orders").fetchone()["n"] == 0


def test_commit_refuses_when_the_proposal_expires_during_lookup(
    monkeypatch, service, agent, request_data
):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    after_lookup(
        monkeypatch,
        lambda: monkeypatch.setattr(workflow, "now", lambda: now() + timedelta(hours=1)),
    )
    assert code_of(lambda: service.commit_order(agent, commit(p))) == "PROPOSAL_EXPIRED"


def test_a_second_commit_with_a_new_key_cannot_create_a_second_order(
    service, agent, request_data, confirm_terms
):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    confirm_terms(p)
    first = service.commit_order(agent, commit(p))
    assert code_of(lambda: service.commit_order(agent, commit(p))) == "ALREADY_COMMITTED"
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM orders").fetchone()["n"] == 1
    assert service.get_order(agent, first["order_id"])["order_id"] == first["order_id"]


# --- decisions -----------------------------------------------------------------------------------


def test_an_agent_cannot_record_a_human_decision(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    assert code_of(lambda: decide(agent, p)) == "FORBIDDEN"
    assert service.get_proposal(agent, p["proposal_id"])["approval_status"] == "pending"


def test_decision_on_an_expired_proposal_is_closed(monkeypatch, service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    monkeypatch.setattr(workflow, "now", lambda: now() + timedelta(hours=1))
    assert code_of(lambda: decide(buyer, p)) == "DECISION_CLOSED"


def test_decision_on_a_committed_proposal_is_closed(service, agent, buyer, mission, confirm_terms):
    p = service.prepare_order(agent, mission)
    confirm_terms(p)
    decide(buyer, p)
    service.commit_order(agent, commit(p))
    assert code_of(lambda: decide(buyer, p, "reject")) == "DECISION_CLOSED"


def test_unknown_approval_is_not_found(buyer):
    assert (
        code_of(
            lambda: workflow.record_human_decision(
                buyer, uuid4(), DecisionRequest(revision=1, decision="approve")
            )
        )
        == "NOT_FOUND"
    )


# --- authorize_commit as a guard ------------------------------------------------------------------


def test_authorize_commit_guards_expiry_and_rejection_on_its_own():
    future, past = now() + timedelta(hours=1), now() - timedelta(minutes=1)
    ready = {"policy_outcome": "ready_to_commit", "required_exceptions": []}

    def run(expires, approval, evaluation=ready):
        workflow.authorize_commit(
            {"expires_at": expires, "fingerprint": "f"}, approval, [], {}, evaluation
        )

    assert code_of(lambda: run(past, None)) == "PROPOSAL_EXPIRED"
    assert code_of(lambda: run(future, {"status": "rejected"})) == "APPROVAL_REJECTED"
    run(future, None)  # ready_to_commit passes without an approval
    blocked = {"policy_outcome": "denied", "required_exceptions": []}
    assert code_of(lambda: run(future, None, blocked)) == "COMMIT_BLOCKED"
    needs = {"policy_outcome": "approval_required", "required_exceptions": ["spend"]}
    assert code_of(lambda: run(future, None, needs)) == "APPROVAL_REQUIRED"


# --- authority drift as seen by readers ----------------------------------------------------------


def test_proposal_with_an_invalid_agent_authority_reads_as_authority_changed(
    service, agent, buyer, mission
):
    p = service.prepare_order(agent, mission)
    with connection() as c:
        c.execute("UPDATE identities SET authority=%s WHERE id='demo-agent'", (js({}),))
    seen = workflow.approval_detail(buyer, p["approval_id"])
    assert seen["approval_status"] == "authority_changed"
    assert seen["can_decide"] is False
    assert seen["next_action"]["type"] != "commit"


def test_approval_by_an_approver_who_lost_authority_no_longer_counts(
    service, agent, buyer, mission
):
    p = service.prepare_order(agent, mission)
    decide(buyer, p)
    assert service.get_proposal(agent, p["proposal_id"])["next_action"]["type"] == "commit"
    with connection() as c:
        c.execute(
            "UPDATE identities SET authority=%s WHERE id='buyer'",
            (js({"currency": "EUR", "max_gross": "100", "exceptions": ["spend"]}),),
        )
    after = service.get_proposal(agent, p["proposal_id"])
    assert after["approval_status"] == "authority_changed"
    assert after["next_action"]["type"] != "commit"


def test_approval_by_an_approver_who_lost_scope_is_void_even_if_another_could_approve(
    service, agent, buyer, mission, confirm_terms
):
    """The policy outcome is unchanged (a second approver is eligible), yet the person who
    approved no longer has the authority their decision relied on."""
    with connection() as c:
        c.execute(
            "INSERT INTO identities VALUES('buyer2','demo-hotel','approver',true,'x',%s)",
            (
                js(
                    {
                        "currency": "EUR",
                        "max_gross": "5000",
                        "exceptions": ["spend", "substitution", "overbuy"],
                    }
                ),
            ),
        )
    p = service.prepare_order(agent, mission)
    confirm_terms(p)
    confirm_terms(p, actor_id="buyer2")  # the second, still eligible approver also confirms
    decide(buyer, p)
    assert service.get_proposal(agent, p["proposal_id"])["next_action"]["type"] == "commit"
    with connection() as c:
        c.execute(
            "UPDATE identities SET authority=%s WHERE id='buyer'",
            (js({"currency": "EUR", "max_gross": "100", "exceptions": []}),),
        )
    after = service.get_proposal(agent, p["proposal_id"])
    assert after["approval_status"] == "authority_changed"
    assert after["next_action"]["type"] != "commit"
    assert code_of(lambda: service.commit_order(agent, commit(p))) == "APPROVAL_REQUIRED"


def test_unknown_order_is_not_found(service, agent):
    assert code_of(lambda: service.get_order(agent, uuid4())) == "NOT_FOUND"
