"""JNP3-CNF-028/033: a disrupted run starts the customer's chat with a system-authored message.

The message tells the agent what is wrong and which lines are still valid ingredients; the agent
is then woken by the ordinary worker path. A failed first turn must never leave the customer
stuck (the conversation would otherwise refuse new messages and have nothing to retry).
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from test_scheduler_engine import at, drive, many, one, run_of, schedule_row, scheduled, widen_scope

from aimo import conversations, scheduler, schedules
from aimo.chat_schemas import AgentTurn, ConversationResponse, MessageRequest
from aimo.db import Problem, connection
from aimo.worker import run_once

pytestmark = pytest.mark.usefixtures("demo_mode")  # these tests start schedules today


@pytest.fixture
def disrupted(buyer, service, connector, placed_order):
    """A schedule whose first run found the product out of stock."""
    s = scheduled(buyer, service, placed_order)
    connector.stock = {"464306": "0"}
    drive(service, at())
    return s


def system_message(cid):
    return one(
        "SELECT * FROM conversation_messages WHERE conversation_id=%s AND role='system'", cid
    )


def test_a_disrupted_run_starts_a_chat_with_a_system_message(buyer, disrupted):
    run = run_of(disrupted)
    assert run["status"] == "disrupted" and run["conversation_id"]
    chat = one("SELECT * FROM conversations WHERE id=%s", run["conversation_id"])
    assert chat["buyer_id"] == "demo-hotel" and "Standing order" in chat["title"]
    messages = many(
        "SELECT role,text FROM conversation_messages WHERE conversation_id=%s", chat["id"]
    )
    assert [m["role"] for m in messages] == ["system"]
    text = messages[0]["text"]
    assert str(run["scheduled_date"]) in text and "PRODUCT_UNAVAILABLE" in text
    assert "464306" in text and "unavailable" in text
    turn = one("SELECT * FROM conversation_turns WHERE conversation_id=%s", chat["id"])
    assert turn["state"] == "queued" and turn["requested_by"] == "buyer"
    assert turn["submitted_by"] is None  # written by the system, not by a person
    detail = conversations.detail(buyer, str(chat["id"]))
    ConversationResponse.model_validate(detail)  # role "system" is part of the wire contract
    assert detail["messages"][0]["role"] == "system" and detail["busy"] is True


def test_the_message_lists_what_is_still_valid_and_what_changed(
    buyer, service, connector, placed_order
):
    widen_scope("464398")
    request_lines = [("464306", "10"), ("464398", "5")]
    from aimo import auth
    from aimo.db import fingerprint
    from aimo.schemas import CommitRequest, PrepareRequest

    base = {
        "request_id": "Two products",
        "idempotency_key": str(uuid4()),
        "destination": "hotel-helsinki",
        "delivery_date": str(date.today() + __import__("datetime").timedelta(days=2)),
        "lines": [{"product_id": p, "amount": a, "unit": "L"} for p, a in request_lines],
    }
    p = service.prepare_order(auth.internal_agent(buyer), PrepareRequest.model_validate(base))
    receipt = conversations.confirm(
        buyer,
        p["proposal_id"],
        CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4())),
        service,
    )
    s = scheduled(buyer, service, {"order_id": receipt["order_id"]})
    connector.stock = {"464306": "0"}
    drive(service, at())
    text = system_message(run_of(s)["conversation_id"])["text"]
    assert text.index("464306") != text.index("464398")
    line_of = {pid: next(x for x in text.splitlines() if pid in x) for pid in ("464306", "464398")}
    assert "unavailable" in line_of["464306"]
    assert "available_same_price" in line_of["464398"]
    assert "valid ingredient" in text  # the instruction to keep the confirmed lines
    assert fingerprint(text)  # plain text only


def test_the_agent_is_woken_by_the_ordinary_worker_path(buyer, service, disrupted):
    cid = str(run_of(disrupted)["conversation_id"])
    seen = []

    def runner(actor, history, svc):
        seen.append(history)
        return AgentTurn(text="Two options for the milk, with the price differences.")

    assert run_once(service, runner) is True
    history = seen[0]
    assert len(history) == 1 and history[0]["role"] == "user"  # the provider sees a user turn
    assert history[0]["content"].startswith("Standing-order notice")
    detail = conversations.detail(buyer, cid)
    assert [m["role"] for m in detail["messages"]] == ["system", "assistant"]
    assert detail["busy"] is False and detail["retry_message"] is None


def test_starting_the_chat_twice_makes_one_conversation(buyer, service, disrupted):
    run = run_of(disrupted)
    with connection() as c:
        auth = c.execute(
            "SELECT * FROM scheduled_authorizations WHERE id=%s", (disrupted["id"],)
        ).fetchone()
        scheduler.start_customer_chat(c, run, auth, "PRODUCT_UNAVAILABLE", run["reason"], at())
    assert one("SELECT count(*) AS n FROM conversations WHERE buyer_id='demo-hotel'")["n"] == 1
    assert one("SELECT count(*) AS n FROM conversation_turns")["n"] == 1


def test_a_failed_first_turn_never_strands_the_customer(buyer, service, disrupted):
    cid = str(run_of(disrupted)["conversation_id"])

    def broken(actor, history, svc):
        raise Problem("LLM_UNAVAILABLE", "The provider is down.", 503)

    with pytest.raises(Problem):
        conversations.execute_turn(conversations.claim_turn(), service, broken)
    detail = conversations.detail(buyer, cid)
    assert [m["role"] for m in detail["messages"]] == ["system", "assistant"]
    fallback = detail["messages"][1]["text"]
    assert "464306" in fallback and "could not" in fallback.lower()
    assert detail["busy"] is False and detail["retry_message"] is None
    # The customer can simply write: nothing is waiting to be retried.
    reply = conversations.enqueue(
        buyer, cid, MessageRequest(text="Use the lactose free milk", idempotency_key=str(uuid4()))
    )
    assert reply["busy"] is True


def test_three_interrupted_attempts_leave_the_same_fallback(buyer, service, disrupted):
    cid = str(run_of(disrupted)["conversation_id"])
    with connection() as c:
        c.execute("UPDATE conversation_turns SET worker_attempts=3")
    assert conversations.claim_turn() is None
    detail = conversations.detail(buyer, cid)
    assert [m["role"] for m in detail["messages"]] == ["system", "assistant"]
    assert detail["retry_message"] is None and detail["busy"] is False


def test_another_customer_cannot_read_the_chat(buyer, service, disrupted):
    cid = str(run_of(disrupted)["conversation_id"])
    from test_schedules import other_buyer

    with pytest.raises(Problem) as refused:
        conversations.detail(other_buyer(), cid)
    assert refused.value.code == "NOT_FOUND"


def test_a_price_disruption_names_both_prices(buyer, service, connector, placed_order):
    s = scheduled(buyer, service, placed_order)
    connector.price_multiplier = Decimal("1.3")
    drive(service, at())
    reason = run_of(s)["reason"]["lines"][0]
    text = system_message(run_of(s)["conversation_id"])["text"]
    assert "price_outside_range" in text
    assert reason["agreed_gross"] in text and reason["current_gross"] in text


def test_no_active_customer_means_no_chat_and_a_recorded_event(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "disrupted" and run["conversation_id"] is None
    events = [e["event"] for e in many("SELECT event FROM scheduled_run_events ORDER BY id")]
    assert "chat_not_started" in events
    assert schedule_row(s)["status"] == "stopped"


def test_a_skipped_run_starts_no_chat(buyer, service, placed_order):
    s = scheduled(buyer, service, placed_order)
    schedules.pause(buyer, s["id"])
    drive(service, at(datetime.now().date()))
    assert one("SELECT count(*) AS n FROM conversations")["n"] == 0
