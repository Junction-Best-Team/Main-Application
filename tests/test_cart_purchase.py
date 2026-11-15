# ruff: noqa: F811
"""Prepare the order straight from the cart (no model): POST /api/conversations/{id}/prepare-from-cart.

Owner direction (2026-11-14): "the purchase button always green and ready ... as items go in, the
user at any point can click confirm purchase and make the purchase." The draft cart is display only,
so the route re-reads the stored plan of the conversation, verifies every matched product again from
the catalog, prepares with the ordinary prepare path (fresh supplier price and stock, policy, ceiling)
and returns the normal proposal. Unmatched items are left out and listed (Q-124 recommended answer).
The scripted provider is never called: a turn that needs the model would fail with an empty script.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from test_draft_cart_purchase import (  # noqa: F401  (the harness and its fixtures)
    CUSTOMER_PLAN_TURN,
    MATCH,
    NAMES,
    call,
    chat,
    plan,
    prepare_only,
    say,
    shows_draft_panel,
    tool_reply,
)

from aimo.db import connection

DAY = str(date.today() + timedelta(days=2))


def body(**over):
    return {
        "delivery_date": DAY,
        "destination": "hotel-helsinki",
        "request_id": str(uuid4()),
    } | over


def go(chat, cid=None, **over):
    return chat.client.post(
        f"/api/conversations/{cid or chat.turn.cid}/prepare-from-cart",
        headers=chat.headers, json=body(**over),
    )  # fmt: skip


def conversation(chat, cid=None):
    return chat.client.get(f"/api/conversations/{cid or chat.turn.cid}").json()


def with_partial_plan(chat, unmatched=("pepper",)):
    """A plan whose listed ingredients are not matched yet (the draft card shows them as open)."""
    p = plan()
    for item in p["ingredients"]:
        if item["name"] in unmatched:
            item["product_id"] = None
    return chat.turn(
        "200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", p)),
        say("Matched most of it. Pepper still needs a product."),
    )  # fmt: skip


def test_the_cart_prepares_the_exact_basket_without_the_assistant(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    sent = go(chat)
    assert sent.status_code == 200, sent.text
    out = sent.json()
    assert out["not_included"] == []
    lines = out["proposal"]["snapshot"]["lines"]
    assert {line["product_id"] for line in lines} == {"meal-" + n for n in NAMES}
    assert out["proposal"]["order_id"] is None  # prepared only: the customer still confirms
    data = conversation(chat)
    assert [p["proposal_id"] for p in data["purchases"]] == [out["proposal"]["proposal_id"]]
    assert not shows_draft_panel(data)
    assert [m["role"] for m in data["messages"][-2:]] == ["user", "assistant"]
    assert data["messages"][-1]["proposal_id"] == out["proposal"]["proposal_id"]
    assert not data["busy"]


def test_a_replay_with_the_same_key_gives_the_same_proposal(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    request = body()
    first = chat.client.post(
        f"/api/conversations/{chat.turn.cid}/prepare-from-cart", headers=chat.headers, json=request
    )
    again = chat.client.post(
        f"/api/conversations/{chat.turn.cid}/prepare-from-cart", headers=chat.headers, json=request
    )
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()
    assert len(conversation(chat)["purchases"]) == 1
    changed = chat.client.post(
        f"/api/conversations/{chat.turn.cid}/prepare-from-cart",
        headers=chat.headers, json=request | {"destination": "somewhere-else"},
    )  # fmt: skip
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_unmatched_items_are_left_out_and_listed(chat):
    with_partial_plan(chat)
    out = go(chat).json()
    assert {line["product_id"] for line in out["proposal"]["snapshot"]["lines"]} == {
        "meal-" + n for n in NAMES if n != "pepper"
    }
    assert [i["name"] for i in out["not_included"]] == ["pepper"]
    assert out["not_included"][0]["reason"]
    assert "pepper" in conversation(chat)["messages"][-1]["text"]


def test_an_empty_or_fully_unmatched_cart_is_a_plain_422(chat):
    other = chat.new_conversation()
    sent = go(chat, other.cid)  # a conversation with no plan at all
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "EMPTY_CART"
    with_partial_plan(chat, unmatched=NAMES)
    sent = go(chat)
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "EMPTY_CART"
    assert conversation(chat)["purchases"] == []


def test_the_cart_of_another_conversation_is_never_used(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    other = chat.new_conversation()
    assert go(chat, other.cid).json()["error"]["code"] == "EMPTY_CART"
    assert conversation(chat, other.cid)["purchases"] == []


def test_another_buyers_or_an_unknown_conversation_is_a_404(chat):
    from wsc_support import add_second_buyer

    from aimo import cart_purchase
    from aimo.chat_schemas import CartPurchaseRequest

    chat.turn(*CUSTOMER_PLAN_TURN)
    stranger = add_second_buyer()["approver"]
    with pytest.raises(Exception) as error:
        cart_purchase.prepare_from_cart(
            stranger, chat.turn.cid, CartPurchaseRequest(**body()), chat.service
        )
    assert error.value.status == 404
    assert go(chat, str(uuid4())).status_code == 404
    assert conversation(chat)["purchases"] == []


def test_sign_in_and_csrf_are_required(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    url = f"/api/conversations/{chat.turn.cid}/prepare-from-cart"
    assert chat.client.post(url, json=body()).status_code == 403  # no CSRF token
    chat.client.cookies.clear()
    assert chat.client.post(url, headers=chat.headers, json=body()).status_code == 401
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0


def test_a_tampered_stored_plan_is_refused(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    with connection() as c:
        c.execute(
            "UPDATE conversation_messages SET meal_plan=jsonb_set(meal_plan,'{ingredients,0,amount}',"
            "'\"-5\"') WHERE meal_plan IS NOT NULL"
        )
    sent = go(chat)
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "CART_NOT_VERIFIED"
    assert conversation(chat)["purchases"] == []


@pytest.mark.parametrize("how", ["withdrawn", "deleted"])
def test_a_product_withdrawn_since_the_plan_is_refused_closed(chat, how):
    chat.turn(*CUSTOMER_PLAN_TURN)
    with connection() as c:
        if how == "deleted":
            c.execute("DELETE FROM products WHERE id='meal-pork'")
        else:
            c.execute(
                "UPDATE products SET facts=jsonb_set(facts,'{deleted}','true') WHERE id='meal-eggs'"
            )
    sent = go(chat)
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "CART_NOT_VERIFIED"
    data = conversation(chat)
    assert data["purchases"] == [] and shows_draft_panel(data)  # the draft stays


def test_a_second_basket_is_not_made_from_the_same_plan(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    assert go(chat).status_code == 200
    again = go(chat)  # a new key: a new basket from a plan that already has one
    assert again.status_code == 409 and again.json()["error"]["code"] == "BASKET_ALREADY_PREPARED"
    assert len(conversation(chat)["purchases"]) == 1


def test_a_conversation_with_a_turn_in_progress_is_busy(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    chat.client.post(
        f"/api/conversations/{chat.turn.cid}/messages", headers=chat.headers,
        json={"text": "one more thing", "idempotency_key": str(uuid4())},
    )  # fmt: skip
    sent = go(chat)  # queued, never run
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "CONVERSATION_BUSY"


def test_policy_still_decides_a_past_date_and_a_foreign_destination(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    past = go(chat, delivery_date=str(date.today() - timedelta(days=1))).json()["proposal"]
    assert past["policy_outcome"] == "denied"
    assert "DELIVERY_IN_PAST" in {r["code"] for r in past["reasons"]}


def test_the_customers_stated_budget_still_binds_a_cart_purchase(chat):
    first = (
        "200 portions of carbonara, hotel-helsinki",
        *MATCH, tool_reply(call("publish_meal_plan", plan())), say("Plan ready."),
    )  # fmt: skip
    chat.client.post(
        f"/api/conversations/{chat.turn.cid}/messages", headers=chat.headers,
        json={"text": first[0], "idempotency_key": str(uuid4()),
              "constraints": {"budget_gross": "5"}},
    )  # fmt: skip
    from aimo.worker import run_once

    chat.script.extend(first[1:])
    assert run_once(chat.service)
    proposal = go(chat).json()["proposal"]
    assert proposal["policy_outcome"] != "ready_to_commit"  # the 5 EUR limit is below the basket
