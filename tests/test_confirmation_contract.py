"""Contract tests for proposal confirmation and receipt (person 3, WS-D).

Each test names the requirement (JNP3-CNF-*, JNP3-PRP-*) it verifies. Everything runs against the
authored fixture catalog and the invented FixtureClient prices: nothing here is live supplier data
and the orders are the demo order service's mock acceptance.

The customer confirms through `conversations.confirm` on a proposal prepared by the buyer's
internal agent, exactly as the browser route does, so the tests keep holding when other agent
identities also need a recorded confirmation.
"""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.config import settings
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest


@pytest.fixture
def actor(buyer):
    return auth.internal_agent(buyer)


def prepared(service, actor, data):
    return service.prepare_order(actor, PrepareRequest.model_validate(data))


def body_for(p, key=None, revision=None):
    return CommitRequest(
        proposal_id=p["proposal_id"],
        revision=revision or p["revision"],
        idempotency_key=key or str(uuid4()),
    )


def rows(sql, args=()):
    with connection() as c:
        return c.execute(sql, args).fetchall()


def count(table):
    return rows(f"SELECT count(*) AS n FROM {table}")[0]["n"]


def code_of(fn):
    with pytest.raises(Problem) as error:
        fn()
    return error.value.code


# --- JNP3-CNF-003, CNF-004: every agent role needs a recorded customer confirmation -------------


@pytest.mark.parametrize("fixture", ["request_data", "mission"])
def test_any_agent_identity_needs_a_recorded_confirmation_to_commit(
    fixture, request, service, buyer, agent
):
    """The retained agent (not the internal one) is refused too, whatever the policy outcome."""
    data = request.getfixturevalue(fixture)
    data = data if isinstance(data, PrepareRequest) else PrepareRequest.model_validate(data)
    p = service.prepare_order(agent, data)
    body = body_for(p)
    assert code_of(lambda: service.commit_order(agent, body)) == "CUSTOMER_CONFIRMATION_REQUIRED"
    if p["approval_id"]:  # a legacy approval decision alone is not a customer confirmation
        workflow.record_human_decision(
            buyer, p["approval_id"], DecisionRequest(revision=1, decision="approve")
        )
        assert code_of(lambda: service.commit_order(agent, body)) == (
            "CUSTOMER_CONFIRMATION_REQUIRED"
        )
    assert count("orders") == 0
    receipt = conversations.confirm(buyer, p["proposal_id"], body, service)
    assert receipt["status"] == "accepted_mock" and count("orders") == 1
    assert service.commit_order(agent, body) == receipt  # the saved receipt replays for the agent


# --- JNP3-CNF-002: a decision is bound to buyer, proposal, revision and terms --------------------


def test_confirmation_binds_buyer_proposal_revision_and_fingerprint(
    service, buyer, actor, request_data
):
    p = prepared(service, actor, request_data)
    body = body_for(p)
    conversations.confirm(buyer, p["proposal_id"], body, service)
    (row,) = rows("SELECT * FROM customer_confirmations")
    (revision,) = rows("SELECT fingerprint FROM proposal_revisions WHERE revision=1")
    assert str(row["proposal_id"]) == p["proposal_id"] and row["revision"] == 1
    assert row["buyer_id"] == buyer["buyer_id"] and row["actor_id"] == buyer["id"]
    assert row["fingerprint"] == revision["fingerprint"] and row["key"] == body.idempotency_key
    # History cannot be rewritten or removed.
    for statement in (
        "UPDATE customer_confirmations SET fingerprint='x'",
        "DELETE FROM customer_confirmations",
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            with connection() as c:
                c.execute(statement)
    assert count("customer_confirmations") == 1


def test_a_foreign_buyer_identity_cannot_confirm(service, buyer, actor, request_data):
    p = prepared(service, actor, request_data)
    foreign = buyer | {"buyer_id": "another-buyer"}
    with pytest.raises(Problem) as error:
        conversations.confirm(foreign, p["proposal_id"], body_for(p), service)
    assert error.value.status in (403, 404)
    assert count("customer_confirmations") == count("orders") == 0


# --- JNP3-CNF-006: commit re-fetches evidence for this proposal's products only ------------------


def recorded_lookups(connector, monkeypatch):
    calls = []
    real = connector.lookup

    def lookup(customer, ids, delivery_date):
        calls.append((customer, list(ids), delivery_date))
        return real(customer, ids, delivery_date)

    monkeypatch.setattr(connector, "lookup", lookup)
    return calls


def test_commit_refetches_only_the_products_of_that_proposal(
    service, connector, buyer, actor, request_data, monkeypatch
):
    request_data["requirements"] = {}
    request_data["lines"] = [{"product_id": "460123", "amount": "10", "unit": "KI"}]
    p = prepared(service, actor, request_data)
    deposits = {d["material"] for d in p["snapshot"]["lines"][0]["deposit_lines"]}
    assert deposits  # the proposal prices a deposit material too
    calls = recorded_lookups(connector, monkeypatch)
    receipt = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert receipt["status"] == "accepted_mock"
    assert len(calls) == 1
    customer, ids, delivery_date = calls[0]
    assert set(ids) == {"460123"} | deposits and len(ids) == len(set(ids))
    assert str(delivery_date) == request_data["delivery_date"]


def test_saved_receipt_is_returned_without_a_supplier_call(
    service, connector, buyer, actor, request_data, monkeypatch
):
    p = prepared(service, actor, request_data)
    body = body_for(p)
    receipt = conversations.confirm(buyer, p["proposal_id"], body, service)
    calls = recorded_lookups(connector, monkeypatch)
    assert conversations.confirm(buyer, p["proposal_id"], body, service) == receipt
    assert calls == []


# --- JNP3-CNF-009 and CNF-008: exception approval and confirmation share exact terms --------------


def test_exception_approval_and_confirmation_share_proposal_revision_and_fingerprint(
    service, buyer, actor, mission
):
    p = service.prepare_order(actor, mission)
    assert p["policy_outcome"] == "approval_required"
    receipt = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert receipt["approval_status"] == "approved" and receipt["revision"] == 1
    (approval,) = rows("SELECT * FROM approvals")
    (confirmation,) = rows("SELECT * FROM customer_confirmations")
    assert approval["status"] == "approved" and approval["actor_id"] == buyer["id"]
    assert (approval["proposal_id"], approval["revision"], approval["fingerprint"]) == (
        confirmation["proposal_id"],
        confirmation["revision"],
        confirmation["fingerprint"],
    )
    assert approval["actor_id"] == confirmation["actor_id"]


def test_confirmation_never_authorizes_a_later_revision(
    service, connector, buyer, actor, request_data
):
    p = prepared(service, actor, request_data)
    connector.price_multiplier = Decimal("1.1")
    revised = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert revised["status"] == "revised" and revised["revision"] == 2
    assert [r["revision"] for r in rows("SELECT revision FROM customer_confirmations")] == [1]
    assert code_of(lambda: service.commit_order(actor, body_for(p, revision=2))) == (
        "CUSTOMER_CONFIRMATION_REQUIRED"
    )
    assert count("orders") == 0


def test_confirmation_does_not_carry_to_a_revision_with_identical_terms(
    service, buyer, actor, request_data, monkeypatch
):
    """Authority-only revisions keep the same fingerprint, so the revision number must bind."""
    from aimo.db import js

    p = prepared(service, actor, request_data)
    body = body_for(p)
    original = service.commit_order

    def supplier_down(*args):
        raise Problem("SUPPLIER_UNAVAILABLE", "Retry after the supplier recovers", 503)

    monkeypatch.setattr(service, "commit_order", supplier_down)
    assert code_of(lambda: conversations.confirm(buyer, p["proposal_id"], body, service)) == (
        "SUPPLIER_UNAVAILABLE"
    )
    monkeypatch.setattr(service, "commit_order", original)
    assert count("customer_confirmations") == 1

    def set_max_gross(value):
        with connection() as c:
            c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (buyer["buyer_id"],))
            c.execute(
                "UPDATE identities SET authority=%s WHERE id=%s",
                (js(buyer["authority"] | {"max_gross": value}), buyer["id"]),
            )

    set_max_gross("1")  # the approver loses authority: same prices, different decision
    assert original(actor, body)["status"] == "revised"
    set_max_gross(buyer["authority"]["max_gross"])
    again = original(actor, body_for(p, revision=2))
    assert again["status"] == "revised" and again["revision"] == 3
    fingerprints = {r["fingerprint"] for r in rows("SELECT fingerprint FROM proposal_revisions")}
    assert len(fingerprints) == 1  # identical terms, three revisions
    assert [r["revision"] for r in rows("SELECT revision FROM customer_confirmations")] == [1]
    assert code_of(lambda: original(actor, body_for(p, revision=3))) == (
        "CUSTOMER_CONFIRMATION_REQUIRED"
    )
    assert count("orders") == 0


# --- JNP3-CNF-016: the policy outcome and the confirmation are separate stored fields -------------


@pytest.mark.parametrize(
    "outcome,fixture,preparer",
    [
        # The internal agent has a zero autonomous limit, so only the retained agent reaches
        # ready_to_commit for the small basket.
        ("ready_to_commit", "request_data", "agent"),
        ("approval_required", "mission", "actor"),
    ],
)
def test_policy_outcome_and_customer_confirmation_are_separate_fields(
    outcome, fixture, preparer, request, service, buyer
):
    # `mission` rewrites the shared `request_data` dict, so request only the one fixture needed.
    data = request.getfixturevalue(fixture)
    p = service.prepare_order(
        request.getfixturevalue(preparer),
        data if isinstance(data, PrepareRequest) else PrepareRequest.model_validate(data),
    )
    assert p["policy_outcome"] == outcome and count("customer_confirmations") == 0
    conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert count("customer_confirmations") == 1
    (stored,) = rows("SELECT policy_outcome FROM proposal_revisions")
    assert stored["policy_outcome"] == outcome  # confirming never rewrites the outcome

    def columns(table):
        return {
            r["column_name"]
            for r in rows(
                "SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,)
            )
        }

    assert "policy_outcome" not in columns("customer_confirmations")
    assert not columns("proposal_revisions") & {"actor_id", "confirmed_at", "key"}


# --- JNP3-PRP-005: every proposal line carries product, quantity and price evidence ---------------


def test_every_proposal_line_has_product_quantity_and_price_evidence(service, actor, mission):
    p = service.prepare_order(actor, mission)
    assert len(p["snapshot"]["lines"]) == 2
    for line in p["snapshot"]["lines"]:
        assert line["product_id"] and line["name"]
        assert line["quantity"]["requested_amount"] and line["quantity"]["sales_quantity"]
        assert line["gross"] and line["net"] and line["tax"] is not None
        assert line["product_evidence"]["id"] == line["product_id"]
        evidence = line["commercial_evidence"]
        assert evidence["gross"] and evidence["source"]["price"]
        assert evidence["expires_at"] and evidence["mode"] == "fixture"


# --- JNP3-CNF-012: no lock or transaction is held across a supplier call -------------------------


def assert_nothing_held(connector, monkeypatch):
    """Wrap lookup: when the supplier is called, another session must be able to take every
    purchasing lock immediately and no pooled session may sit inside an open transaction."""
    seen = []
    real = connector.lookup

    def lookup(customer, ids, delivery_date):
        with psycopg.connect(settings().database_url) as other:
            other.execute("SET lock_timeout='300ms'")
            for table in ("buyers", "identities", "proposals", "approvals"):
                other.execute(f"SELECT 1 FROM {table} FOR UPDATE").fetchall()
            (idle,) = other.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() AND state LIKE 'idle in transaction%%'"
            ).fetchone()
        seen.append(idle)
        return real(customer, ids, delivery_date)

    monkeypatch.setattr(connector, "lookup", lookup)
    return seen


def test_no_lock_or_open_transaction_during_prepare_and_commit_supplier_calls(
    service, connector, buyer, actor, request_data, monkeypatch
):
    seen = assert_nothing_held(connector, monkeypatch)
    p = prepared(service, actor, request_data)
    assert seen == [0]
    receipt = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert receipt["status"] == "accepted_mock"
    assert seen == [0, 0]  # prepare once, the confirmation's commit once


# --- JNP3-CNF-013: the commit path needs no LLM provider or network client ------------------------


def test_commit_path_modules_do_not_import_the_agent():
    code = (
        "import sys\n"
        "import aimo.approval_workflow, aimo.approval_policy, aimo.purchases, aimo.service\n"
        "import aimo.conversations\n"
        "bad = [m for m in ('aimo.agent', 'aimo.agent_provider', 'aimo.agent_tools') "
        "if m in sys.modules]\n"
        "sys.exit('agent modules imported: ' + ','.join(bad) if bad else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=os.environ.copy(), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-500:]


def test_confirmation_and_receipt_make_no_outbound_http_call(
    service, buyer, actor, request_data, monkeypatch
):
    import httpx

    p = prepared(service, actor, request_data)

    def forbidden(*args, **kwargs):
        raise AssertionError("the commit path must not call a provider or any HTTP client")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(settings(), "llm_api_key", "")
    receipt = conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
    assert receipt["status"] == "accepted_mock" and receipt["upstream_order_placed"] is False


# --- JNP3-CNF-019: concurrent confirmations and a confirmation racing a repricing ----------------


def test_concurrent_confirmations_with_one_key_create_one_order(
    service, buyer, actor, request_data
):
    p = prepared(service, actor, request_data)
    body = body_for(p)
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(
            pool.map(
                lambda _: conversations.confirm(buyer, p["proposal_id"], body, service), range(8)
            )
        )
    assert len({r["order_id"] for r in receipts}) == 1 and all(r == receipts[0] for r in receipts)
    assert count("orders") == count("customer_confirmations") == count("idempotency") == 1


def test_concurrent_confirmations_with_different_keys_create_one_order(
    service, buyer, actor, request_data
):
    p = prepared(service, actor, request_data)

    def confirm(_):
        try:
            return conversations.confirm(buyer, p["proposal_id"], body_for(p), service)
        except Problem as error:
            return error.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(confirm, range(6)))
    receipts = [r for r in results if isinstance(r, dict)]
    assert len(receipts) >= 1 and len({r["order_id"] for r in receipts}) == 1
    assert set(r for r in results if isinstance(r, str)) <= {"DECISION_CLOSED", "ALREADY_COMMITTED"}
    assert count("orders") == count("customer_confirmations") == 1


def test_confirmation_racing_a_repricing_never_orders_another_revision(
    service, connector, buyer, actor, request_data, monkeypatch
):
    p = prepared(service, actor, request_data)
    first, second = body_for(p), body_for(p)
    real = connector.lookup
    state = {"calls": 0, "revised": None}

    def lookup(customer, ids, delivery_date):
        state["calls"] += 1
        if state["calls"] == 1:
            # While the first caller waits on the supplier, prices move and another caller's
            # commit appends revision 2. Nesting proves no lock is held by the first caller.
            connector.price_multiplier = Decimal("1.1")
            state["revised"] = service.commit_order(actor, second)
        return real(customer, ids, delivery_date)

    monkeypatch.setattr(connector, "lookup", lookup)
    assert code_of(lambda: conversations.confirm(buyer, p["proposal_id"], first, service)) == (
        "STALE_REVISION"
    )
    assert state["revised"]["status"] == "revised" and state["revised"]["revision"] == 2
    assert count("orders") == 0
    assert [r["revision"] for r in rows("SELECT revision FROM customer_confirmations")] == [1]
    assert workflow.get_proposal(buyer, p["proposal_id"])["current_revision"] == 2
    assert code_of(lambda: service.commit_order(actor, body_for(p, revision=2))) == (
        "CUSTOMER_CONFIRMATION_REQUIRED"
    )


# --- JNP3-CNF-011 (Draft wording, owner 2026-11-14): a repeat returns the receipt whatever its key ---


# CNF-011 (Approved): any repeated confirmation of an ordered proposal returns the saved receipt.
def test_repeated_confirmation_with_another_key_returns_the_saved_receipt(
    service, connector, buyer, actor, request_data, monkeypatch
):
    p = prepared(service, actor, request_data)
    first = conversations.confirm(
        buyer, p["proposal_id"], body_for(p, key="confirm-key-A"), service
    )
    calls = recorded_lookups(connector, monkeypatch)
    second = conversations.confirm(
        buyer, p["proposal_id"], body_for(p, key="confirm-key-B"), service
    )
    assert second == first
    assert calls == []  # and still no supplier work
    assert count("orders") == count("customer_confirmations") == 1


def test_prior_result_any_key_finds_the_saved_receipt_of_the_ordered_revision(
    service, buyer, actor, request_data, monkeypatch
):
    """Workflow half of CNF-011: the lookup that conversations.confirm will use for any key."""
    p = prepared(service, actor, request_data)
    first = conversations.confirm(buyer, p["proposal_id"], body_for(p, key="key-AAAAA"), service)
    other_key = body_for(p, key="key-BBBBB")

    def lookup(body, **kwargs):
        with connection() as c:
            return workflow.prior_result(c, buyer, body, **kwargs)

    assert lookup(other_key) is None  # the commit path keeps ALREADY_COMMITTED for a new key
    assert lookup(other_key, any_key=True) == first
    assert (
        lookup(body_for(p, key="key-AAAAA"), any_key=True) == first
    )  # the original key still works
    # Terms the order was not placed on never get the receipt.
    assert lookup(body_for(p, key="key-CCCCC", revision=2), any_key=True) is None
    # A key already used for other terms is still a conflict, not a receipt.
    q = prepared(service, actor, request_data | {"idempotency_key": str(uuid4())})

    def supplier_down(*args):
        raise Problem("SUPPLIER_UNAVAILABLE", "down", 503)

    original = service.commit_order
    monkeypatch.setattr(service, "commit_order", supplier_down)
    assert code_of(
        lambda: conversations.confirm(
            buyer, q["proposal_id"], body_for(q, key="key-DDDDD"), service
        )
    ) == ("SUPPLIER_UNAVAILABLE")
    monkeypatch.setattr(service, "commit_order", original)
    assert code_of(lambda: lookup(body_for(p, key="key-DDDDD"), any_key=True)) == (
        "IDEMPOTENCY_CONFLICT"
    )
    # A proposal with no order has nothing to return.
    assert lookup(body_for(q, key="key-EEEEE"), any_key=True) is None
