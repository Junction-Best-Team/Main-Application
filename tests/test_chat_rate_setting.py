"""The hourly message limit of an account is a setting (CHAT_MESSAGES_PER_HOUR), default 60.

Production behaviour is unchanged unless a deployment sets the variable: with the default the 61st
new message inside an hour is refused (429 CHAT_RATE_LIMIT); raising the setting lets it through.
Accepted retries and confirmation turns never counted and still do not.
"""

from uuid import uuid4

import pytest

from aimo import conversations
from aimo.chat_schemas import ConversationCreate, MessageRequest
from aimo.config import Settings, settings
from aimo.db import Problem, connection


def conversation_with_recent_turns(buyer, count):
    cid = conversations.create(
        buyer, ConversationCreate(title="rate", idempotency_key=str(uuid4()))
    )["id"]
    with connection() as c:
        for n in range(count):
            c.execute(
                """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
                attempt,requested_by,worker_attempts,submitted_by) VALUES(%s,%s,%s,'h','complete',now(),%s,%s,0,%s)""",
                (uuid4(), cid, f"seed-{n}", uuid4(), buyer["id"], buyer["id"]),
            )
    return cid


def send(buyer, cid):
    return conversations.enqueue(
        buyer, cid, MessageRequest(text="one more", idempotency_key=str(uuid4()))
    )


def test_the_default_is_sixty():
    assert Settings.model_fields["chat_messages_per_hour"].default == 60
    assert settings().chat_messages_per_hour == 60


def test_with_the_default_the_sixty_first_message_in_an_hour_is_refused(buyer):
    cid = conversation_with_recent_turns(buyer, 60)
    with pytest.raises(Problem) as error:
        send(buyer, cid)
    assert error.value.code == "CHAT_RATE_LIMIT" and error.value.status == 429


def test_the_sixtieth_message_is_still_accepted(buyer):
    cid = conversation_with_recent_turns(buyer, 59)
    assert send(buyer, cid)["busy"] is True


def test_a_setting_of_200_lets_the_sixty_first_through(buyer, monkeypatch):
    monkeypatch.setattr(settings(), "chat_messages_per_hour", 200)
    cid = conversation_with_recent_turns(buyer, 60)
    assert send(buyer, cid)["busy"] is True
    with connection() as c:
        c.execute("DELETE FROM conversation_turns WHERE key LIKE 'seed-%'")  # keep the table tidy


def test_the_setting_still_has_a_ceiling(buyer, monkeypatch):
    monkeypatch.setattr(settings(), "chat_messages_per_hour", 200)
    cid = conversation_with_recent_turns(buyer, 200)
    with pytest.raises(Problem) as error:
        send(buyer, cid)
    assert error.value.code == "CHAT_RATE_LIMIT"


@pytest.mark.parametrize("value", [0, -1, 2001])
def test_the_setting_range_is_one_to_two_thousand(value):
    with pytest.raises(ValueError):
        Settings(chat_messages_per_hour=value)
    assert Settings(chat_messages_per_hour=1).chat_messages_per_hour == 1
    assert Settings(chat_messages_per_hour=2000).chat_messages_per_hour == 2000


# --- the unfinished turns one account may have at once (CHAT_ACTIVE_TURNS_PER_BUYER, default 3) ---------


def queued_turns(buyer, count):
    cid = conversations.create(
        buyer, ConversationCreate(title="busy", idempotency_key=str(uuid4()))
    )["id"]
    with connection() as c:
        for n in range(count):
            other = uuid4()
            c.execute(
                "INSERT INTO conversations(id,buyer_id,title,create_key,create_hash) "
                "SELECT %s,buyer_id,'q',%s,'h' FROM conversations WHERE id=%s",
                (other, f"q-{uuid4()}", cid),
            )
            c.execute(
                """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
                attempt,requested_by,worker_attempts,submitted_by) VALUES(%s,%s,%s,'h','queued',now(),%s,%s,0,%s)""",
                (uuid4(), other, f"queued-{n}", uuid4(), buyer["id"], buyer["id"]),
            )
    return cid


def test_the_active_turns_default_is_three_and_the_fourth_is_refused(buyer):
    assert Settings.model_fields["chat_active_turns_per_buyer"].default == 3
    cid = queued_turns(buyer, 3)
    with pytest.raises(Problem) as error:
        send(buyer, cid)
    assert error.value.code == "CHAT_BUSY" and error.value.status == 429


def test_two_queued_turns_leave_room_for_a_third(buyer):
    cid = queued_turns(buyer, 2)
    assert send(buyer, cid)["busy"] is True


def test_a_setting_of_six_allows_more_unfinished_turns(buyer, monkeypatch):
    monkeypatch.setattr(settings(), "chat_active_turns_per_buyer", 6)
    cid = queued_turns(buyer, 3)
    assert send(buyer, cid)["busy"] is True


@pytest.mark.parametrize("value", [0, -1, 13])
def test_the_active_turns_range_is_one_to_twelve(value):
    with pytest.raises(ValueError):
        Settings(chat_active_turns_per_buyer=value)
    assert Settings(chat_active_turns_per_buyer=1).chat_active_turns_per_buyer == 1
    assert Settings(chat_active_turns_per_buyer=12).chat_active_turns_per_buyer == 12
