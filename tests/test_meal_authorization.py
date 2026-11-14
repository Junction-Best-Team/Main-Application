"""JNP3-POL-010: withdraw a per-meal authorization when the recipe is edited or unconfirmed.

A per-meal authorization is the customer's approval of one proposal revision (an approved
`approvals` row or a stored `customer_confirmations` row). It is never granted by the agent,
expires with the proposal and never touches the standing product list. Withdrawal is a Service
operation for the authenticated customer; it is not an agent tool. Fixture mode only.
"""

from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from pydantic import ValidationError
from wsc_support import add_second_buyer, counts

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo import meal_authorization as meals
from aimo.db import Problem, connection, now
from aimo.meal_authorization import WithdrawMealAuthorization
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest


def commit_body(p, revision=None):
    return CommitRequest(
        proposal_id=p["proposal_id"],
        revision=revision or p["revision"],
        idempotency_key=str(uuid4()),
    )


def withdraw(service, who, pid, reason="Recipe edited"):
    return service.withdraw_meal_authorization(
        who, WithdrawMealAuthorization(proposal_id=pid, reason=reason)
    )


def code_of(fn):
    with pytest.raises(Problem) as error:
        fn()
    return error.value.code


def orders():
    with connection() as c:
        return c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]


def policy_rows():
    with connection() as c:
        return c.execute("SELECT * FROM policies ORDER BY buyer_id,version").fetchall()


def approve(buyer, p):
    return workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=p["revision"], decision="approve")
    )


# --- granting is only ever the customer's approval of a revision ---------------------------


def test_agent_preparation_alone_grants_nothing(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    state = service.get_meal_authorization(buyer, p["proposal_id"])
    assert state["status"] == "not_granted"
    assert state["product_ids"] == ["464306", "464398"]
    assert state["granted_by"] is None


def test_customer_approval_grants_for_exactly_the_approved_revision(
    service, agent, buyer, mission
):
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    state = service.get_meal_authorization(buyer, p["proposal_id"])
    assert state["status"] == "active"
    assert state["granted_by"] == "buyer" and state["revision"] == 1
    assert state["proposal_id"] == p["proposal_id"] and state["withdrawn_at"] is None
    assert state["expires_at"] == p["expires_at"]  # expires with the proposal


# --- withdrawal ------------------------------------------------------------------------------


def test_withdrawal_after_approval_blocks_commit_and_supersedes_the_approval(
    service, agent, buyer, mission
):
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    assert service.get_proposal(agent, p["proposal_id"])["next_action"]["type"] == "commit"
    result = withdraw(service, buyer, p["proposal_id"])
    assert result["status"] == "withdrawn" and result["withdrawn_by"] == "buyer"
    assert result["reason"] == "Recipe edited" and result["withdrawn_at"] is not None
    assert code_of(lambda: service.commit_order(agent, commit_body(p))) == "AUTHORIZATION_WITHDRAWN"
    assert orders() == 0
    seen = service.get_proposal(agent, p["proposal_id"])
    assert seen["approval_status"] == "authorization_withdrawn"
    assert seen["next_action"]["type"] == "request_fresh_proposal"
    with connection() as c:
        assert c.execute("SELECT status FROM approvals").fetchone()["status"] == "superseded"
    assert service.get_meal_authorization(buyer, p["proposal_id"])["status"] == "withdrawn"
    # The same basket is not silently usable again: a fresh proposal needs a fresh decision.
    fresh = service.prepare_order(
        agent, mission.model_copy(update={"idempotency_key": str(uuid4())})
    )
    assert fresh["proposal_id"] != p["proposal_id"] and fresh["policy_outcome"] == "approval_required"
    assert fresh["approval_status"] == "pending"


def test_withdrawal_before_approval_prevents_the_decision(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    withdraw(service, buyer, p["proposal_id"])
    assert code_of(lambda: approve(buyer, p)) == "DECISION_CONFLICT"
    assert code_of(lambda: service.commit_order(agent, commit_body(p))) == "AUTHORIZATION_WITHDRAWN"
    assert orders() == 0


def test_withdrawal_blocks_a_ready_to_commit_basket_too(service, agent, buyer, request_data):
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "ready_to_commit"
    withdraw(service, buyer, p["proposal_id"])
    assert code_of(lambda: service.commit_order(agent, commit_body(p))) == "AUTHORIZATION_WITHDRAWN"
    assert orders() == 0


def test_withdrawal_after_a_customer_confirmation_that_could_not_commit(
    service, buyer, request_data, monkeypatch
):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    real_commit = service.commit_order

    def unavailable(*args):
        raise Problem("SUPPLIER_UNAVAILABLE", "Retry later", 503)

    monkeypatch.setattr(service, "commit_order", unavailable)
    first = commit_body(p)
    assert code_of(lambda: conversations.confirm(buyer, p["proposal_id"], first, service)) == (
        "SUPPLIER_UNAVAILABLE"
    )
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 1
    assert service.get_meal_authorization(buyer, p["proposal_id"])["status"] == "active"
    withdraw(service, buyer, p["proposal_id"], "Customer unconfirmed the recipe")
    monkeypatch.setattr(service, "commit_order", real_commit)
    assert code_of(lambda: service.commit_order(internal, first)) == "AUTHORIZATION_WITHDRAWN"
    retry = commit_body(p)
    assert code_of(lambda: conversations.confirm(buyer, p["proposal_id"], retry, service)) in (
        "AUTHORIZATION_WITHDRAWN",
        "DECISION_CLOSED",
    )
    assert orders() == 0


def test_withdrawal_is_idempotent_and_audited_once(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    first = withdraw(service, buyer, p["proposal_id"], "first reason")
    again = withdraw(service, buyer, p["proposal_id"], "second reason")
    assert again == first and again["reason"] == "first reason"
    with connection() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM meal_authorization_withdrawals").fetchone()["n"]
            == 1
        )
        events = c.execute(
            "SELECT actor_id,detail FROM audit_events WHERE event='meal_authorization_withdrawn'"
        ).fetchall()
    assert len(events) == 1 and events[0]["actor_id"] == "buyer"
    assert events[0]["detail"]["revision"] == 1 and events[0]["detail"]["reason"] == "first reason"


def test_withdraw_by_recipe_plan_finds_the_linked_proposal(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    recipe, plan = "wsc-" + uuid4().hex, uuid4()
    with connection() as c:
        c.execute("INSERT INTO recipes VALUES(%s)", (recipe,))
        c.execute(
            "INSERT INTO recipe_versions(recipe_id,version,data,source,source_version,"
            "source_hash,attribution,license) VALUES(%s,'1','{}','test','1','h','a','l')",
            (recipe,),
        )
        c.execute(
            "INSERT INTO recipe_plans(id,buyer_id,agent_id,turn_id,recipe_id,recipe_version,"
            "portions,proposal_id,locked) VALUES(%s,'demo-hotel','demo-agent','t1',%s,'1',200,%s,true)",
            (plan, recipe, p["proposal_id"]),
        )
    result = service.withdraw_meal_authorization(
        buyer, WithdrawMealAuthorization(plan_id=plan, reason="Recipe changed")
    )
    assert result["status"] == "withdrawn" and result["plan_id"] == str(plan)
    assert result["proposal_id"] == p["proposal_id"]
    assert code_of(lambda: service.commit_order(agent, commit_body(p))) == "AUTHORIZATION_WITHDRAWN"


def test_plan_without_a_proposal_has_nothing_to_withdraw(service, buyer):
    recipe, plan = "wsc-" + uuid4().hex, uuid4()
    with connection() as c:
        c.execute("INSERT INTO recipes VALUES(%s)", (recipe,))
        c.execute(
            "INSERT INTO recipe_versions(recipe_id,version,data,source,source_version,"
            "source_hash,attribution,license) VALUES(%s,'1','{}','test','1','h','a','l')",
            (recipe,),
        )
        c.execute(
            "INSERT INTO recipe_plans(id,buyer_id,agent_id,turn_id,recipe_id,recipe_version,"
            "portions) VALUES(%s,'demo-hotel','demo-agent','t2',%s,'1',200)",
            (plan, recipe),
        )
    result = service.withdraw_meal_authorization(
        buyer, WithdrawMealAuthorization(plan_id=plan, reason="Recipe changed")
    )
    assert result["status"] == "not_granted" and result["proposal_id"] is None
    with connection() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM meal_authorization_withdrawals").fetchone()["n"]
            == 0
        )


def test_committed_purchase_cannot_be_withdrawn(service, agent, buyer, mission, confirm_terms):
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    confirm_terms(p)
    receipt = service.commit_order(agent, commit_body(p))
    assert receipt["status"] == "accepted_mock"
    assert code_of(lambda: withdraw(service, buyer, p["proposal_id"])) == "ALREADY_COMMITTED"
    assert orders() == 1


def test_expiry_ends_the_authorization_without_a_withdrawal(service, agent, buyer, mission, monkeypatch):
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    monkeypatch.setattr(meals, "now", lambda: now() + timedelta(hours=1))
    state = service.get_meal_authorization(buyer, p["proposal_id"])
    assert state["status"] == "expired" and state["withdrawn_at"] is None


# --- who may withdraw ------------------------------------------------------------------------


def test_only_the_buyers_authenticated_customer_may_withdraw(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    internal = auth.internal_agent(buyer)
    other = add_second_buyer()
    before = counts()
    for who in (agent, internal):
        with pytest.raises(Problem) as error:
            withdraw(service, who, p["proposal_id"])
        assert (error.value.code, error.value.status) == ("FORBIDDEN", 403)
    for who in (other["approver"], other["agent"], other["internal"]):
        assert code_of(lambda who=who: withdraw(service, who, p["proposal_id"])) in (
            "NOT_FOUND",
            "FORBIDDEN",
        )
    assert counts() == before
    assert service.get_meal_authorization(buyer, p["proposal_id"])["status"] == "active"


def test_other_buyer_cannot_read_the_authorization(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    other = add_second_buyer()
    assert code_of(
        lambda: service.get_meal_authorization(other["approver"], p["proposal_id"])
    ) == "NOT_FOUND"


def test_revoked_customer_cannot_withdraw(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    assert code_of(lambda: withdraw(service, buyer, p["proposal_id"])) == "AUTHORITY_REVOKED"


def test_request_needs_exactly_one_target_and_a_reason():
    with pytest.raises(ValidationError):
        WithdrawMealAuthorization(reason="x")
    with pytest.raises(ValidationError):
        WithdrawMealAuthorization(proposal_id=uuid4(), plan_id=uuid4(), reason="x")
    with pytest.raises(ValidationError):
        WithdrawMealAuthorization(proposal_id=uuid4(), reason="")
    with pytest.raises(ValidationError):
        WithdrawMealAuthorization(proposal_id=uuid4(), reason="x", buyer_id="other")


# --- invariants ------------------------------------------------------------------------------


def test_withdrawal_never_changes_the_standing_product_list(service, agent, buyer, mission):
    before = policy_rows()
    p = service.prepare_order(agent, mission)
    approve(buyer, p)
    withdraw(service, buyer, p["proposal_id"])
    assert policy_rows() == before
    assert before[-1]["rules"]["approved_product_ids"] == ["464306"]


def test_withdrawal_records_are_append_only(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    withdraw(service, buyer, p["proposal_id"])
    for statement in (
        "UPDATE meal_authorization_withdrawals SET reason='edited'",
        "DELETE FROM meal_authorization_withdrawals",
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            with connection() as c:
                c.execute(statement)


def test_withdrawal_is_not_an_agent_tool():
    from aimo.agent_tools import ToolSession

    class Stub:
        def __getattr__(self, name):
            raise AssertionError("agent tools must not reach " + name)

    identity = {"id": "internal:x", "buyer_id": "demo-hotel", "role": "agent", "_turn_id": "t"}
    tools = ToolSession(identity, Stub())
    assert "withdraw_meal_authorization" not in tools.registry
    assert code_of(lambda: tools.invoke("withdraw_meal_authorization", "{}")) == "TOOL_NOT_ALLOWED"


def test_migration_ten_is_additive_and_registered():
    with connection() as c:
        assert c.execute(
            "SELECT 1 FROM schema_migrations WHERE version='010_meal_authorization_withdrawals.sql'"
        ).fetchone()
        columns = {
            r["column_name"]
            for r in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='meal_authorization_withdrawals'"
            ).fetchall()
        }
    assert {"proposal_id", "buyer_id", "plan_id", "revision", "withdrawn_by", "reason"} <= columns
