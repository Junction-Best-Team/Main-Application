# ruff: noqa: F811
"""The items a basket leaves out stay on the card after a reload (owner Q-124 a): GET conversation has
`cart_not_included`, computed from the latest stored plan against the current basket, never stored
separately: an item without a product, without a quantity, or removed by the customer on the card.
"""

from uuid import uuid4

from test_cart_auto_prepare import EDIT, auto, baskets, data, edited_turn, more  # noqa: F401
from test_cart_edit import put  # noqa: F401
from test_draft_cart_purchase import CUSTOMER_PLAN_TURN, MATCH, call, chat, plan, say, tool_reply  # noqa: F401

from aimo.db import connection


def partial(unmatched=("pepper",)):
    p = plan()
    for item in p["ingredients"]:
        if item["name"] in unmatched:
            item["product_id"] = None
    return p


def with_pepper_open(auto):
    return auto.turn(
        "200 portions of carbonara", *MATCH,
        tool_reply(call("publish_meal_plan", partial())), say("Pepper still needs a product."),
    )  # fmt: skip


def listed(d):
    return [(i["name"], i["amount"], i["unit"], i["reason"]) for i in d["cart_not_included"]]


def confirm(auto, basket):
    sent = auto.client.post(
        f"/api/purchases/{basket['proposal_id']}/confirm", headers=auto.headers,
        json={"proposal_id": basket["proposal_id"], "revision": basket["revision"],
              "idempotency_key": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 200, sent.text


def test_an_item_without_a_product_is_listed_and_survives_a_reload(auto):
    d = with_pepper_open(auto)
    assert len(baskets(d)) == 1  # the basket was prepared without pepper
    assert listed(d) == [("pepper", "0.2", "KG", "no_product")]
    assert listed(data(auto)) == listed(data(auto)) == [("pepper", "0.2", "KG", "no_product")]


def test_the_item_disappears_from_the_list_once_it_is_matched(auto):
    with_pepper_open(auto)
    only_pepper = [
        tool_reply(call("search_products", {"query": "pepper"})),
        tool_reply(call("get_product", {"product_id": "meal-pepper"})),
    ]
    d = auto.turn("use that pepper", *only_pepper, tool_reply(call("publish_meal_plan", plan())),
                  say("Matched."))  # fmt: skip
    assert listed(d) == [] and listed(data(auto)) == []
    assert len(baskets(d)) == 2  # the matched cart made a new basket


def test_a_removed_line_is_listed_as_removed_and_comes_back_off_the_list(auto):
    auto.turn(*CUSTOMER_PLAN_TURN)
    assert listed(data(auto)) == []
    put(auto, [("cheese", 0)])
    assert listed(data(auto)) == [("cheese", "0", "KG", "removed")]
    put(auto, [("cheese", 4)])
    assert listed(data(auto)) == []


def test_an_item_without_a_quantity_is_listed_as_no_quantity(auto):
    auto.turn(*CUSTOMER_PLAN_TURN)
    with connection() as c:
        c.execute(
            "UPDATE conversation_messages SET meal_plan=jsonb_set(meal_plan,'{ingredients,4,amount}','null')"
            " WHERE meal_plan IS NOT NULL"
        )
    assert listed(data(auto)) == [("pepper", None, "KG", "no_quantity")]


def test_after_an_order_the_list_is_empty(auto):
    d = with_pepper_open(auto)
    assert listed(d)
    confirm(auto, baskets(d)[0])
    assert data(auto)["cart_not_included"] == []


def test_without_a_basket_there_is_no_list(chat):
    d = chat.turn(  # auto-prepare is off in the plain chat fixture: the draft card shows the items
        "200 portions of carbonara", *MATCH,
        tool_reply(call("publish_meal_plan", partial())), say("Pepper still needs a product."),
    )  # fmt: skip
    assert baskets(d) == [] and d["cart_not_included"] == []


def test_another_conversation_is_not_affected(auto):
    with_pepper_open(auto)
    other = auto.new_conversation()
    d = other(*CUSTOMER_PLAN_TURN)
    assert d["cart_not_included"] == []
    assert listed(data(auto)) == [("pepper", "0.2", "KG", "no_product")]


def test_a_saved_recipe_cart_and_an_empty_conversation_have_no_list(auto):
    assert data(auto)["cart_not_included"] == []
    auto.turn(*CUSTOMER_PLAN_TURN)
    with connection() as c:
        c.execute(
            "UPDATE conversation_messages SET meal_plan=jsonb_set(meal_plan,'{recipe_plan_id}',"
            "to_jsonb(%s::text)) WHERE meal_plan IS NOT NULL",
            (str(uuid4()),),
        )
    assert data(auto)["cart_not_included"] == []


def test_a_plan_newer_than_the_basket_does_not_describe_the_old_basket(auto):
    with_pepper_open(auto)
    assert listed(data(auto))
    with connection() as c:  # a cancelled basket is not "the current basket"
        c.execute(
            "INSERT INTO order_request_cancellations(proposal_id,buyer_id,reason,cancelled_by) "
            "SELECT p.id,p.buyer_id,'customer_cancelled',(SELECT id FROM identities WHERE role='approver' "
            "AND buyer_id=p.buyer_id LIMIT 1) FROM proposals p"
        )
    assert data(auto)["cart_not_included"] == []
