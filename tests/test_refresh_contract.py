"""Refresh contract for recipe-backed proposals (person 3, WS-D).

A refresh of an expired recipe-backed proposal appends revision N+1 to the SAME proposal
(PR #38). These tests pin what that means for customer confirmation, approval, the saved
receipt, preparation idempotency and lock/transaction hygiene.

Requirements: JNP3-CNF-008, JNP3-CNF-010, JNP3-CNF-011, JNP3-CNF-012, JNP3-PRP-004
(migration 007). Authored recipe fixtures and the invented FixtureClient prices only; the
orders are the demo order service's mock acceptance.
"""

from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

# Reuse the recipe test helpers and fixtures (authored fixtures, no live supplier).
from test_recipes import (  # noqa: F401  (fixtures are used by name)
    clean_recipes,
    import_fixture,
    match_all,
    meal_products,
    ref,
    request_for,
)

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.config import settings
from aimo.db import Problem, connection
from aimo.recipe_schemas import PlanReference
from aimo.recipes import get_plan, scale_recipe
from aimo.schemas import CommitRequest


@pytest.fixture
def actor(buyer):
    return auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}


def count(table):
    with connection() as c:
        return c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def code_of(fn):
    with pytest.raises(Problem) as error:
        fn()
    return error.value.code


@pytest.fixture
def refreshed(request, tmp_path, buyer, actor, service, monkeypatch):
    """Revision 1 prepared and confirmed (the order attempt failed), then expired and refreshed
    in place to revision 2 by a later agent turn."""
    request.getfixturevalue("meal_products")
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    first_request = request_for(plan)
    first = service.prepare_order(actor, first_request)
    body = CommitRequest(proposal_id=first["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    real_commit = service.commit_order

    def supplier_down(*args):
        raise Problem("SUPPLIER_UNAVAILABLE", "down", 503)

    monkeypatch.setattr(service, "commit_order", supplier_down)
    with pytest.raises(Problem) as error:
        conversations.confirm(buyer, first["proposal_id"], body, service)
    assert error.value.code == "SUPPLIER_UNAVAILABLE"
    monkeypatch.setattr(service, "commit_order", real_commit)
    with connection() as c:
        assert count("customer_confirmations") == 1
        approval = c.execute("SELECT status FROM approvals WHERE revision=1").fetchone()
    real_now = workflow.now
    monkeypatch.setattr(workflow, "now", lambda: real_now() + timedelta(hours=1))
    later = actor | {"_turn_id": str(uuid4())}
    refresh_request = request_for(get_plan(later, PlanReference(plan_id=plan["recipe_plan_id"])))
    fresh = service.prepare_order(later, refresh_request)
    monkeypatch.setattr(workflow, "now", real_now)
    fresh = service.get_proposal(actor, fresh["proposal_id"])
    return {
        "plan": plan,
        "first": first,
        "fresh": fresh,
        "approval_status": approval["status"],
        "body": body,
        "first_request": first_request,
        "refresh_request": refresh_request,
    }


def new_key(body, **update):
    return body.model_copy(update={"revision": 2, "idempotency_key": str(uuid4())} | update)


# --- JNP3-CNF-008: a confirmation and approval are bound to one revision -------------------------


def test_old_confirmation_and_approval_do_not_attach_to_the_refreshed_revision(
    buyer, actor, service, refreshed
):
    first, fresh, body = refreshed["first"], refreshed["fresh"], refreshed["body"]
    assert refreshed["approval_status"] == "approved"  # revision 1 had an exception approval
    assert fresh["proposal_id"] == first["proposal_id"] and fresh["revision"] == 2
    assert fresh["approval_status"] == "pending" and fresh["approval_id"] != first["approval_id"]
    with connection() as c:
        old = c.execute("SELECT status FROM approvals WHERE revision=1").fetchone()["status"]
        revisions = [
            r["revision"] for r in c.execute("SELECT revision FROM customer_confirmations")
        ]
    assert old == "superseded" and revisions == [1]
    # Revision 2 has no confirmation of its own, so even the agent cannot commit it.
    code = code_of(
        lambda: service.commit_order(
            actor,
            CommitRequest(
                proposal_id=first["proposal_id"], revision=2, idempotency_key=str(uuid4())
            ),
        )
    )
    assert code == "CUSTOMER_CONFIRMATION_REQUIRED" and count("orders") == 0
    # The old key cannot be replayed onto revision 2.
    replay = body.model_copy(update={"revision": 2})
    code = code_of(lambda: conversations.confirm(buyer, first["proposal_id"], replay, service))
    assert code == "IDEMPOTENCY_CONFLICT" and count("orders") == 0
    # A new key confirms revision 2 and yields its receipt.
    receipt = conversations.confirm(buyer, first["proposal_id"], new_key(body), service)
    assert receipt["revision"] == 2 and receipt["status"] == "accepted_mock"
    assert count("orders") == 1 and count("customer_confirmations") == 2


# --- JNP3-CNF-010, CNF-011: an ordered plan is final ---------------------------------------------


def test_refresh_after_order_is_refused_and_the_receipt_is_stable(buyer, actor, service, refreshed):
    first, body, plan = refreshed["first"], refreshed["body"], refreshed["plan"]
    receipt = conversations.confirm(buyer, first["proposal_id"], new_key(body), service)
    later = actor | {"_turn_id": str(uuid4())}
    code = code_of(
        lambda: service.prepare_order(
            later, request_for(get_plan(later, PlanReference(plan_id=plan["recipe_plan_id"])))
        )
    )
    assert code == "RECIPE_PLAN_LOCKED"
    assert service.get_order(actor, receipt["order_id"]) == receipt
    assert count("orders") == 1 and count("proposal_revisions") == 2


# --- JNP3-PRP-004, migration 007: several preparation keys per proposal --------------------------


def test_a_refreshed_proposal_keeps_preparation_idempotency_per_key(actor, service, refreshed):
    first = refreshed["first"]
    with connection() as c:
        keys = c.execute("SELECT key,proposal_id FROM prepare_requests").fetchall()
        constraints = {
            r["conname"]
            for r in c.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid='prepare_requests'::regclass"
            )
        }
    assert len(keys) == 2 and len({str(k["proposal_id"]) for k in keys}) == 1
    assert "prepare_requests_pkey" in constraints  # buyer/agent/key still enforces idempotency
    # The first key still resolves to the same proposal.
    again = service.prepare_order(actor, refreshed["first_request"])
    assert again["proposal_id"] == first["proposal_id"]
    # The same key with changed terms is still a conflict.
    changed = refreshed["first_request"].model_copy(update={"destination": "other"})
    assert code_of(lambda: service.prepare_order(actor, changed)) == "IDEMPOTENCY_CONFLICT"
    changed = refreshed["refresh_request"].model_copy(update={"destination": "other"})
    assert code_of(lambda: service.prepare_order(actor, changed)) == "IDEMPOTENCY_CONFLICT"
    assert count("proposals") == 1


# --- JNP3-CNF-012: a recipe-backed preparation holds no lock across the supplier call ------------


@pytest.mark.usefixtures("meal_products")
def test_recipe_backed_prepare_holds_no_buyer_or_plan_lock_during_the_supplier_call(
    tmp_path, actor, service, connector, monkeypatch
):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    seen = []
    real = connector.lookup

    def lookup(customer, ids, delivery_date):
        with psycopg.connect(settings().database_url) as other:
            other.execute("SET lock_timeout='300ms'")
            for table in ("buyers", "identities", "proposals", "recipe_plans"):
                other.execute(f"SELECT 1 FROM {table} FOR UPDATE").fetchall()
            (idle,) = other.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() AND state LIKE 'idle in transaction%%'"
            ).fetchone()
        seen.append(idle)
        return real(customer, ids, delivery_date)

    monkeypatch.setattr(connector, "lookup", lookup)
    prepared = service.prepare_order(actor, request_for(plan))
    assert seen == [0] and prepared["revision"] == 1
