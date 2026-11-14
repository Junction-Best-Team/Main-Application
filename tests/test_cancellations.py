"""CNF-035 / CNF-034: an order REQUEST (a proposal) can be cancelled; a placed order never can.

Orders stay immutable (CNF-020), so "cancelled" is a separate append-only record keyed by the
proposal. Fixture catalog and invented FixtureClient prices only; every order is a mock
("Accepted by demo order service").
"""

from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo import cancellations, conversations
from aimo.db import Problem, connection, js
from aimo.schemas import CommitRequest, PrepareRequest


def commit_request(p):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )


@pytest.fixture
def proposal(service, agent, request_data):
    return service.prepare_order(agent, PrepareRequest(**request_data))


@pytest.fixture
def other_buyer():
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other-hotel','456',1) ON CONFLICT DO NOTHING")
        rules = c.execute(
            "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
        ).fetchone()["rules"]
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('other-hotel',1,%s) "
            "ON CONFLICT DO NOTHING",
            (js(rules),),
        )
        c.execute(
            """INSERT INTO identities VALUES('other-approver','other-hotel','approver',true,'!x',
            '{"currency":"EUR","max_gross":"5000.00","exceptions":[]}') ON CONFLICT DO NOTHING"""
        )
        return c.execute("SELECT * FROM identities WHERE id='other-approver'").fetchone()


def count(table):
    with connection() as c:
        return c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_a_customer_cancels_a_pending_request_and_the_record_names_who_and_why(proposal, buyer):
    result = cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    assert result["proposal_id"] == proposal["proposal_id"]
    assert result["reason"] == "customer_cancelled"
    with connection() as c:
        row = c.execute(
            "SELECT * FROM order_request_cancellations WHERE proposal_id=%s",
            (proposal["proposal_id"],),
        ).fetchone()
    assert row["buyer_id"] == buyer["buyer_id"] and row["cancelled_by"] == buyer["id"]
    assert row["reason"] == "customer_cancelled" and row["run_id"] is None


def test_cancelling_twice_is_idempotent_and_keeps_the_first_record(proposal, buyer):
    first = cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    again = cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    assert again == first
    assert count("order_request_cancellations") == 1


def test_an_agent_cannot_cancel_a_request_for_the_customer(proposal, agent):
    with pytest.raises(Problem) as error:
        cancellations.cancel_my_request(agent, proposal["proposal_id"])
    assert error.value.code == "FORBIDDEN" and error.value.status == 403
    assert count("order_request_cancellations") == 0


def test_another_buyers_request_is_not_found(proposal, other_buyer):
    with pytest.raises(Problem) as error:
        cancellations.cancel_my_request(other_buyer, proposal["proposal_id"])
    assert error.value.code == "NOT_FOUND" and error.value.status == 404
    assert count("order_request_cancellations") == 0


def test_a_placed_order_cannot_be_cancelled(service, agent, buyer, proposal):
    service.commit_order(buyer, commit_request(proposal))
    with pytest.raises(Problem) as error:
        cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    assert error.value.code == "ORDER_ALREADY_PLACED" and error.value.status == 409
    assert count("order_request_cancellations") == 0
    assert count("orders") == 1


def test_the_database_also_refuses_to_cancel_a_placed_order(service, buyer, proposal):
    service.commit_order(buyer, commit_request(proposal))
    with connection() as c, pytest.raises(Exception, match="placed order cannot be cancelled"):
        c.execute(
            """INSERT INTO order_request_cancellations(proposal_id,buyer_id,reason,cancelled_by)
            VALUES(%s,%s,'customer_cancelled',%s)""",
            (proposal["proposal_id"], buyer["buyer_id"], buyer["id"]),
        )


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE order_request_cancellations SET reason='run_retry'",
        "DELETE FROM order_request_cancellations",
    ],
)
def test_a_cancellation_is_append_only(proposal, buyer, sql):
    cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    with connection() as c, pytest.raises(Exception, match="immutable"):
        c.execute(sql)


def test_the_engine_records_a_reason_and_a_run_and_ignores_a_repeat(proposal, buyer):
    with connection() as c:
        first = cancellations.cancel_request(
            c,
            proposal_id=proposal["proposal_id"],
            buyer_id=buyer["buyer_id"],
            reason="run_disrupted",
            by=buyer["id"],
        )
        again = cancellations.cancel_request(
            c,
            proposal_id=proposal["proposal_id"],
            buyer_id=buyer["buyer_id"],
            reason="run_retry",
            by=buyer["id"],
        )
    assert first is True and again is False  # the first record stands
    with connection() as c:
        row = c.execute("SELECT reason FROM order_request_cancellations").fetchone()
    assert row["reason"] == "run_disrupted"


def test_an_unknown_reason_is_refused(proposal, buyer):
    with connection() as c, pytest.raises(ValueError):
        cancellations.cancel_request(
            c,
            proposal_id=proposal["proposal_id"],
            buyer_id=buyer["buyer_id"],
            reason="because",
            by=buyer["id"],
        )


def test_a_cancelled_request_cannot_be_committed(service, buyer, proposal):
    cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    with pytest.raises(Problem) as error:
        service.commit_order(buyer, commit_request(proposal))
    assert error.value.code == "REQUEST_CANCELLED" and error.value.status == 409
    assert count("orders") == 0


def test_a_cancelled_request_cannot_be_confirmed_in_the_browser(service, buyer, proposal):
    cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    body = commit_request(proposal)
    with pytest.raises(Problem) as error:
        conversations.confirm(buyer, proposal["proposal_id"], body, service)
    assert error.value.code == "REQUEST_CANCELLED"
    assert count("orders") == 0 and count("customer_confirmations") == 0


def test_the_proposal_view_says_cancelled(service, buyer, proposal):
    cancellations.cancel_my_request(buyer, proposal["proposal_id"])
    view = workflow.get_proposal(buyer, proposal["proposal_id"])
    assert view["approval_status"] == "cancelled"
    assert view["order_status"] == "not_placed"
    assert view["next_action"] == {"type": "stop"}


def test_a_cancelled_request_leaves_the_approval_inbox(service, agent, buyer, mission):
    waiting = service.prepare_order(agent, mission)
    assert waiting["approval_status"] == "pending"
    inbox = [i["proposal_id"] for i in workflow.list_approvals(buyer, 0, 20)["items"]]
    assert waiting["proposal_id"] in inbox
    cancellations.cancel_my_request(buyer, waiting["proposal_id"])
    inbox = [i["proposal_id"] for i in workflow.list_approvals(buyer, 0, 20)["items"]]
    assert waiting["proposal_id"] not in inbox
