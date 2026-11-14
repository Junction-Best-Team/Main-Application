"""Owner Q-121: a message after the customer confirms, and only then.

When the customer's confirm route places an order, the conversation that holds the basket gets ONE
plain system-authored line (role `system`, notice `order_confirmed`): demo order accepted, delivery
date, in the language of the customer's last message. No model call, no raw error text; a replay, a
revised or a failed confirm adds nothing; the scheduler's own commit writes none. The line is for
the customer: the model's history leaves it out (like the provider-failure notice). Fixture mode.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from aimo import auth, conversations, scheduler
from aimo.chat_schemas import AgentTurn, ConversationCreate, ConversationResponse, MessageRequest
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, PrepareRequest


def chat_with_basket(buyer, service, request_data, customer_text="I need milk for the weekend"):
    """A conversation whose assistant reply carries a prepared basket, as a real chat turn does."""
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    made = {}

    def runner(actor, history, svc, **kwargs):
        p = svc.prepare_order(
            actor, PrepareRequest.model_validate(request_data | {"idempotency_key": str(uuid4())})
        )
        made["proposal"] = p
        return AgentTurn(text="Here is the basket.", proposal_id=p["proposal_id"])

    conversations.message(
        buyer,
        cid,
        MessageRequest(text=customer_text, idempotency_key=str(uuid4())),
        service,
        runner,
    )
    return cid, made["proposal"]


def confirm(service, buyer, proposal, key=None, revision=1):
    body = CommitRequest(
        proposal_id=proposal["proposal_id"], revision=revision, idempotency_key=key or str(uuid4())
    )
    return conversations.confirm(buyer, proposal["proposal_id"], body, service)


def notices(cid):
    with connection() as c:
        return c.execute(
            "SELECT * FROM conversation_messages WHERE conversation_id=%s AND notice='order_confirmed'"
            " ORDER BY id",
            (cid,),
        ).fetchall()


def test_confirming_an_order_stores_one_plain_system_line_in_that_chat(
    buyer, service, request_data
):
    cid, proposal = chat_with_basket(buyer, service, request_data)
    receipt = confirm(service, buyer, proposal)
    (line,) = notices(cid)
    assert line["role"] == "system" and line["proposal_id"] is None
    assert str(request_data["delivery_date"]) not in line["text"]  # a readable date, not ISO
    assert "demo" in line["text"].lower() and "delivery" in line["text"].lower()
    assert receipt["label"] == "Accepted by demo order service"
    detail = conversations.detail(buyer, cid)
    ConversationResponse.model_validate(detail)  # role system and the notice are in the contract
    assert detail["messages"][-1]["role"] == "system"
    assert detail["messages"][-1]["notice"] == "order_confirmed" and detail["busy"] is False


def test_the_line_names_the_delivery_date_of_the_proposal(buyer, service, request_data):
    request_data["delivery_date"] = "2026-11-17"
    cid, proposal = chat_with_basket(buyer, service, request_data)
    confirm(service, buyer, proposal)
    assert "17 Nov." in notices(cid)[0]["text"]


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("I need milk for the weekend", "Order accepted by the demo order service"),
        ("Hei, tarvitsen maitoa ja kermaa hotellille", "Tilaus hyväksytty"),
        ("Hej, jag vill beställa mjölk och grädde", "Beställningen godtogs"),
        ("???", "Order accepted by the demo order service"),  # unsure: English
    ],
)
def test_the_line_is_in_the_language_of_the_customers_last_message(
    buyer, service, request_data, text, needle
):
    request_data["delivery_date"] = "2026-11-17"
    cid, proposal = chat_with_basket(buyer, service, request_data, text)
    confirm(service, buyer, proposal)
    assert needle in notices(cid)[0]["text"]


def test_a_replay_with_the_same_key_or_another_adds_nothing(buyer, service, request_data):
    cid, proposal = chat_with_basket(buyer, service, request_data)
    key = str(uuid4())
    first = confirm(service, buyer, proposal, key)
    assert confirm(service, buyer, proposal, key) == first
    assert confirm(service, buyer, proposal) == first  # any key returns the saved receipt
    assert len(notices(cid)) == 1


def test_a_revised_confirm_adds_nothing_and_the_final_one_adds_one(
    buyer, service, connector, request_data
):
    cid, proposal = chat_with_basket(buyer, service, request_data)
    connector.price_multiplier = Decimal("1.1")  # the terms move: the confirm answers "revised"
    revised = confirm(service, buyer, proposal)
    assert revised["status"] == "revised" and notices(cid) == []
    final = confirm(service, buyer, proposal, revision=revised["revision"])
    assert final["status"] == "accepted_mock" and len(notices(cid)) == 1


@pytest.mark.parametrize("why", ["stale", "blocked", "wrong_role"])
def test_a_failed_confirm_adds_nothing_and_shows_no_error_text(buyer, service, request_data, why):
    if why == "blocked":
        request_data = request_data | {"budget_gross": "1"}  # denied: the hard budget
    cid, proposal = chat_with_basket(buyer, service, request_data)
    who, revision = buyer, 1
    if why == "stale":
        revision = 7
    elif why == "wrong_role":
        who = auth.internal_agent(buyer)
    with pytest.raises(Problem):
        conversations.confirm(
            who,
            proposal["proposal_id"],
            CommitRequest(
                proposal_id=proposal["proposal_id"], revision=revision, idempotency_key=str(uuid4())
            ),
            service,
        )
    assert notices(cid) == []
    texts = [m["text"] for m in conversations.detail(buyer, cid)["messages"]]
    assert not any("error" in t.lower() or "STALE" in t for t in texts)


def test_a_basket_that_is_in_no_chat_stores_nothing_and_still_confirms(
    buyer, service, request_data
):
    p = service.prepare_order(
        auth.internal_agent(buyer),
        PrepareRequest.model_validate(request_data | {"idempotency_key": str(uuid4())}),
    )
    assert confirm(service, buyer, p)["status"] == "accepted_mock"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM conversation_messages").fetchone()["n"] == 0


def test_the_scheduler_commit_writes_no_line(buyer, service, placed_order, demo_mode):
    from test_scheduler_engine import at, drive, scheduled

    scheduled(buyer, service, placed_order)
    drive(service, at())
    with connection() as c:
        n = c.execute(
            "SELECT count(*) AS n FROM conversation_messages WHERE notice='order_confirmed'"
        ).fetchone()["n"]
    assert n == 0 and scheduler


def test_the_model_never_sees_the_line_and_the_chat_can_go_on(buyer, service, request_data):
    cid, proposal = chat_with_basket(buyer, service, request_data)
    confirm(service, buyer, proposal)
    seen = []

    def runner(actor, history, svc, **kwargs):
        seen.append([m["content"] for m in history])
        return AgentTurn(text="Anything else?")

    conversations.message(
        buyer,
        cid,
        MessageRequest(text="Thanks, and one more thing", idempotency_key=str(uuid4())),
        service,
        runner,
    )
    assert not any("demo order service" in text for text in seen[0])
    roles = [m["role"] for m in conversations.detail(buyer, cid)["messages"]]
    assert roles.count("system") == 1 and roles[-1] == "assistant"


def test_the_line_does_not_count_against_the_hourly_message_limit(
    buyer, service, request_data, monkeypatch
):
    monkeypatch.setattr(conversations, "MAX_MESSAGES_PER_HOUR", 2)
    cid, proposal = chat_with_basket(buyer, service, request_data)  # one customer turn
    confirm(service, buyer, proposal)
    reply = conversations.message(
        buyer,
        cid,
        MessageRequest(text="And a second message", idempotency_key=str(uuid4())),
        service,
        lambda *a, **k: AgentTurn(text="Sure."),
    )
    assert reply["messages"][-1]["text"] == "Sure."
    assert timedelta(0) is not None
