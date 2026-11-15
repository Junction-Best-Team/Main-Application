"""Reads and the chat turn must never fail on odd stored data (investigation of a reported send error).

Derived fields (the simulated fulfilment status) and the stored-plan restore are conveniences: if
the stored data they read is missing or malformed they must fall back (no fulfilment, no restored
plan), never raise. A raise here surfaces as an unhandled error on every read of the conversation.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wsc_support import login_headers

from aimo import auth, conversations
from aimo.api import create_app
from aimo.db import connection
from aimo.schemas import CommitRequest, PrepareRequest


def ordered(service, buyer, request_data):
    actor = auth.internal_agent(buyer)
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    return p, conversations.confirm(buyer, p["proposal_id"], body, service)


def drop_from_request(proposal_id, key=None, value=None):
    """Alter the stored request of the order's revision (the history trigger is bypassed for the test)."""
    with connection() as c:
        c.execute("ALTER TABLE proposal_revisions DISABLE TRIGGER USER")
        if value is None:
            c.execute(
                "UPDATE proposal_revisions SET request = request - %s WHERE proposal_id=%s",
                (key, proposal_id),
            )
        else:
            c.execute(
                "UPDATE proposal_revisions SET request = jsonb_set(request, %s, %s::jsonb) "
                "WHERE proposal_id=%s",
                ([key], value, proposal_id),
            )
        c.execute("ALTER TABLE proposal_revisions ENABLE TRIGGER USER")


@pytest.mark.parametrize(
    "tamper",
    [("delivery_date", None), ("delivery_date", '"not a date"'), ("delivery_date", "null")],
    ids=["missing", "not-a-date", "null"],
)
def test_an_order_without_a_usable_delivery_date_still_reads_without_a_fulfilment(
    service, buyer, request_data, tamper
):
    p, receipt = ordered(service, buyer, request_data)
    drop_from_request(p["proposal_id"], *tamper)
    with TestClient(create_app(service), raise_server_exceptions=False) as client:
        login_headers(client)
        got = client.get(f"/api/purchases/{p['proposal_id']}/receipt")
        assert got.status_code == 200, got.text
        assert got.json()["order_id"] == receipt["order_id"] and got.json()["fulfilment"] is None
        assert got.json()["delivery_date"] is None
        items = client.get("/api/orders?status=placed")
        assert items.status_code == 200, items.text
        assert [i["fulfilment"] for i in items.json()["items"]] == [None]


def test_a_stored_purchase_that_no_longer_fits_the_models_does_not_break_the_conversation(
    service, buyer, request_data
):
    """One unreadable purchase is left out of the conversation, and the chat still works."""
    good, _ = ordered(service, buyer, request_data)
    broken, _ = ordered(service, buyer, dict(request_data, idempotency_key=str(uuid4())))
    drop_from_request(
        broken["proposal_id"], "delivery_date"
    )  # a request the response model rejects
    with TestClient(create_app(service), raise_server_exceptions=False) as client:
        headers = login_headers(client)
        cid = client.post(
            "/api/conversations",
            headers=headers,
            json={"title": "t", "idempotency_key": "k-conv-001"},
        ).json()["id"]
        first = client.post(
            f"/api/conversations/{cid}/messages",
            headers=headers,
            json={"text": "hei", "idempotency_key": "k-msg-0001"},
        )
        assert first.status_code == 200, first.text
        with connection() as c:
            for p in (good, broken):
                c.execute(
                    "INSERT INTO conversation_messages(conversation_id,turn_id,role,text,proposal_id) "
                    "SELECT %s,t.id,'assistant','basket',%s FROM conversation_turns t "
                    "WHERE t.conversation_id=%s AND NOT EXISTS (SELECT 1 FROM conversation_messages m "
                    "WHERE m.turn_id=t.id AND m.role='assistant') LIMIT 1",
                    (cid, p["proposal_id"], cid),
                )
            c.execute(
                "UPDATE conversation_turns SET state='complete' WHERE conversation_id=%s", (cid,)
            )
            # the second link needs its own turn slot: link it to a later turn
            c.execute(
                "INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,"
                "attempt,requested_by,worker_attempts,submitted_by) "
                "SELECT gen_random_uuid(),%s,'k-msg-0002','h','complete',now(),gen_random_uuid(),"
                "'buyer',0,'buyer'",
                (cid,),
            )
            c.execute(
                "INSERT INTO conversation_messages(conversation_id,turn_id,role,text,proposal_id) "
                "SELECT %s,t.id,'assistant','basket 2',%s FROM conversation_turns t "
                "WHERE t.conversation_id=%s AND t.key='k-msg-0002'",
                (cid, broken["proposal_id"], cid),
            )
        shown = client.get(f"/api/conversations/{cid}")
        assert shown.status_code == 200, shown.text
        assert [p["proposal_id"] for p in shown.json()["purchases"]] == [good["proposal_id"]]
        again = client.post(
            f"/api/conversations/{cid}/messages",
            headers=headers,
            json={"text": "vielä", "idempotency_key": "k-msg-0003"},
        )
        assert again.status_code == 200, again.text


def plan(**kw):
    return {
        "title": "Carbonara",
        "portions": 4,
        "ingredients": [{"name": "spaghetti", "amount": "1", "unit": "kg", "product_id": "464306"}],
    } | kw


@pytest.mark.parametrize(
    "stored",
    [
        plan(ingredients=["spaghetti"]),
        plan(ingredients={"name": "spaghetti"}),
        plan(ingredients=5),
        plan(ingredients=[None]),
        "a plan, as text",
        ["not", "a", "dict"],
        5,
    ],
    ids=["strings", "dict", "int", "none-item", "text", "list", "int-plan"],
)
def test_a_malformed_stored_plan_is_never_offered_and_never_raises(stored):
    messages = [
        {"role": "user", "meal_plan": None, "proposal_id": None, "notice": None},
        {"role": "assistant", "meal_plan": stored, "proposal_id": None, "notice": None},
    ]
    assert conversations.restorable_plan(messages) is None


def test_a_complete_stored_plan_is_still_offered():
    messages = [{"role": "assistant", "meal_plan": plan(), "proposal_id": None, "notice": None}]
    assert conversations.restorable_plan(messages) == plan()
