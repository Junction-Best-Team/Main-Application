# ruff: noqa: F811
"""The customer edits the PACK COUNT of a basket line on the card: PUT /api/conversations/{id}/cart.

The server only changes quantities of products already in the stored cart (never adds one), keeps a
removed product in the stored plan with amount "0" (so it can come back), prepares the basket again
(older open basket cancelled atomically) and makes the edit visible to the assistant so its next turn does
not undo it. Fixture products are sold per KG with 1 KG per sales unit, so packs equal kilograms here.
"""

from uuid import uuid4

import pytest
from test_cart_auto_prepare import (  # noqa: F401
    EDIT,
    auto,
    baskets,
    data,
    edited_turn,
    more,
    state,
)
from test_draft_cart_purchase import (  # noqa: F401
    CUSTOMER_PLAN_TURN,
    NAMES,
    call,
    chat,
    plan,
    say,
    shows_draft_panel,
    tool_reply,
)

from aimo.db import connection


def put(chat, lines, cid=None, key=None, headers=True):
    return chat.client.put(
        f"/api/conversations/{cid or chat.turn.cid}/cart",
        headers=chat.headers if headers else {},
        json={"request_id": key or str(uuid4()),
              "lines": [{"product_id": "meal-" + n, "sales_quantity": q} for n, q in lines]},
    )  # fmt: skip


def lines_of(basket):
    return {i["product_id"]: i["quantity"]["sales_quantity"] for i in basket["snapshot"]["lines"]}


def start(auto):
    return baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]


def test_a_pack_count_edit_makes_a_new_basket_with_exactly_that_many_packs(auto):
    first = start(auto)
    sent = put(auto, [("pepper", 3)])
    assert sent.status_code == 200, sent.text
    out = sent.json()
    assert lines_of(out["proposal"])["meal-pepper"] == "3"
    assert lines_of(out["proposal"])["meal-pasta"] == lines_of(first)["meal-pasta"]
    d = data(auto)
    by_id = {b["proposal_id"]: b for b in baskets(d)}
    assert state(by_id[first["proposal_id"]]) == "cancelled"
    assert [b["proposal_id"] for b in baskets(d) if state(b) != "cancelled"] == [
        out["proposal"]["proposal_id"]
    ]
    assert [m["role"] for m in d["messages"][-2:]] == ["user", "assistant"]
    assert d["messages"][-1]["proposal_id"] == out["proposal"]["proposal_id"]
    assert [i["amount"] for i in d["messages"][-1]["meal_plan"]["ingredients"]][-1] == "3"


def test_zero_leaves_the_line_out_but_keeps_the_product_and_it_can_come_back(auto):
    start(auto)
    out = put(auto, [("cheese", 0)]).json()
    assert "meal-cheese" not in lines_of(out["proposal"])
    assert [(i["name"], i["reason"]) for i in out["not_included"]] == [("cheese", "removed")]
    stored = {
        i["product_id"]: i["amount"] for i in data(auto)["messages"][-1]["meal_plan"]["ingredients"]
    }
    assert stored["meal-cheese"] == "0"  # still in the stored plan
    back = put(auto, [("cheese", 4)]).json()
    assert lines_of(back["proposal"])["meal-cheese"] == "4" and back["not_included"] == []


def test_a_product_that_is_not_in_the_cart_is_never_added(auto):
    start(auto)
    sent = auto.client.put(
        f"/api/conversations/{auto.turn.cid}/cart", headers=auto.headers,
        json={"request_id": str(uuid4()), "lines": [{"product_id": "464306", "sales_quantity": 5}]},
    )  # fmt: skip
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "ITEM_NOT_IN_CART"
    assert sent.json()["error"]["details"]["product_id"] == "464306"
    assert len(baskets(data(auto))) == 1


def test_removing_every_line_changes_nothing(auto):
    first = start(auto)
    sent = put(auto, [(n, 0) for n in NAMES])
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "EMPTY_CART"
    d = data(auto)
    assert [b["proposal_id"] for b in baskets(d)] == [first["proposal_id"]]
    assert state(baskets(d)[0]) != "cancelled"


def test_unchanged_quantities_give_the_current_basket_and_no_new_revision(auto):
    start(auto)
    changed = put(auto, [("pepper", 3)]).json()["proposal"]
    again = put(auto, [("pepper", 3)])  # a new key, same numbers: nothing to change
    assert again.status_code == 200
    assert again.json()["proposal"]["proposal_id"] == changed["proposal_id"]
    assert len(baskets(data(auto))) == 2  # the first basket and the edited one; no third


def test_replay_gives_the_same_basket_and_a_changed_replay_conflicts(auto):
    start(auto)
    key = str(uuid4())
    one = put(auto, [("pepper", 3)], key=key)
    two = put(auto, [("pepper", 3)], key=key)
    assert one.status_code == two.status_code == 200 and two.json() == one.json()
    assert len(baskets(data(auto))) == 2
    clash = put(auto, [("pepper", 4)], key=key)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "lines",
    [
        [{"product_id": "meal-pepper", "sales_quantity": -1}],
        [{"product_id": "meal-pepper", "sales_quantity": 1.5}],
        [{"product_id": "meal-pepper", "sales_quantity": 100001}],
        [{"product_id": "meal-pepper", "sales_quantity": "x"}],
        [{"product_id": "meal-pepper", "sales_quantity": 1}] * 2,
        [],
    ],
)
def test_malformed_quantities_are_refused_before_anything_happens(auto, lines):
    start(auto)
    sent = auto.client.put(
        f"/api/conversations/{auto.turn.cid}/cart", headers=auto.headers,
        json={"request_id": str(uuid4()), "lines": lines},
    )  # fmt: skip
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "VALIDATION_ERROR"
    assert len(baskets(data(auto))) == 1


def test_another_conversation_another_buyer_and_no_session_are_refused(auto):
    from wsc_support import add_second_buyer

    from aimo import cart_purchase
    from aimo.chat_schemas import CartEditRequest

    start(auto)
    other = auto.new_conversation()
    assert put(auto, [("pepper", 3)], cid=other.cid).json()["error"]["code"] == "EMPTY_CART"
    stranger = add_second_buyer()["approver"]
    body = CartEditRequest(
        request_id=str(uuid4()), lines=[{"product_id": "meal-pepper", "sales_quantity": 3}]
    )
    with pytest.raises(Exception) as error:
        cart_purchase.edit_cart(stranger, auto.turn.cid, body, auto.service)
    assert error.value.status == 404
    assert put(auto, [("pepper", 3)], cid=str(uuid4())).status_code == 404
    assert put(auto, [("pepper", 3)], headers=False).status_code == 403
    auto.client.cookies.clear()
    assert put(auto, [("pepper", 3)]).status_code == 401
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 1


def test_a_tampered_stored_plan_is_refused(auto):
    start(auto)
    with connection() as c:
        c.execute(
            "UPDATE conversation_messages SET meal_plan=jsonb_set(meal_plan,'{ingredients,0,amount}',"
            "'\"-5\"') WHERE meal_plan IS NOT NULL"
        )
    sent = put(auto, [("pepper", 3)])
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "CART_NOT_VERIFIED"


def test_a_conversation_with_a_turn_in_progress_is_busy(auto):
    start(auto)
    auto.client.post(
        f"/api/conversations/{auto.turn.cid}/messages", headers=auto.headers,
        json={"text": "one more thing", "idempotency_key": str(uuid4())},
    )  # fmt: skip
    sent = put(auto, [("pepper", 3)])
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "CONVERSATION_BUSY"


def test_confirming_the_basket_that_was_edited_away_gets_revised(auto):
    first = start(auto)
    put(auto, [("pepper", 3)])
    sent = auto.client.post(
        f"/api/purchases/{first['proposal_id']}/confirm", headers=auto.headers,
        json={"proposal_id": first["proposal_id"], "revision": first["revision"],
              "idempotency_key": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "REQUEST_REVISED"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


def test_the_assistant_is_told_about_the_edit_and_its_next_turn_keeps_the_number(auto):
    start(auto)
    put(auto, [("pepper", 3), ("cheese", 0)])
    p = plan()  # the model republishes what it was shown: pepper 3, cheese kept at 0
    for item in p["ingredients"]:
        item["amount"] = {"pepper": "3", "cheese": "0"}.get(item["name"], item["amount"])
    d = auto.turn("thanks, also keep it cold", tool_reply(call("publish_meal_plan", p)),
                  say("Noted, the cart stays as you set it."))  # fmt: skip
    shown = str(auto.seen[-1])
    assert "I changed the cart" in shown and "pepper" in shown and "cheese" in shown
    assert "'amount': '3'" in shown or '"amount": "3"' in shown
    open_now = [b for b in baskets(d) if state(b) != "cancelled"]
    assert len(open_now) == 1 and lines_of(open_now[0])["meal-pepper"] == "3"
    assert "meal-cheese" not in lines_of(open_now[0])  # the removal is not undone


def test_a_model_prepare_after_a_removal_buys_only_the_kept_lines(auto):
    from test_draft_cart_purchase import prepared

    start(auto)
    put(auto, [("cheese", 0)])
    p = plan()
    for item in p["ingredients"]:
        if item["name"] == "cheese":
            item["amount"] = "0"
    order = prepared()
    order["lines"] = [line for line in order["lines"] if line["product_id"] != "meal-cheese"]
    order["delivery_date"] = data(auto)["purchases"][-1]["request"]["delivery_date"]
    d = auto.turn("order it", tool_reply(call("publish_meal_plan", p)),
                  tool_reply(call("prepare_order", order)), say("Review the basket."))  # fmt: skip
    latest = [b for b in baskets(d) if state(b) != "cancelled"][0]
    assert "meal-cheese" not in lines_of(latest) and len(lines_of(latest)) == 4


def test_a_saved_recipe_cart_cannot_be_edited_yet_and_says_why(auto):
    with connection() as c:
        c.execute("SELECT 1")
    d = data(auto)
    assert d["cart_editable"] is False and d["cart_edit_reason"]  # no cart yet
    start(auto)
    d = data(auto)
    assert d["cart_editable"] is True and d["cart_edit_reason"] is None
    with connection() as c:
        c.execute(
            "UPDATE conversation_messages SET meal_plan=jsonb_set(meal_plan,'{recipe_plan_id}',"
            "to_jsonb(%s::text)) WHERE meal_plan IS NOT NULL",
            (str(uuid4()),),
        )
    locked = data(auto)
    assert locked["cart_editable"] is False and "saved recipe" in locked["cart_edit_reason"]
    sent = put(auto, [("pepper", 3)])
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "RECIPE_BASKET_LOCKED"
