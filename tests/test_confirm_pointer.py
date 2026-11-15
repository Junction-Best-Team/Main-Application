# ruff: noqa: F811
"""Whenever a basket exists after a turn, the reply points to the Confirm purchase button (round 1: 3 scenarios lacked it).

The trusted notice already says so for an open basket; a blocked, denied or needs-resolution basket, and a
basket made after the model's turn by the server, had no pointer. The server appends ONE fixed sentence
when the reply lacks it; a basket that already has an order gets none.
"""

from datetime import date, timedelta

from test_cart_auto_prepare import auto, baskets  # noqa: F401
from test_draft_cart_purchase import (  # noqa: F401
    CUSTOMER_PLAN_TURN,
    MATCH,
    call,
    chat,
    plan,
    prepared,
    say,
    tool_reply,
)

POINTER = "Confirm purchase"
CARD = "Your order"  # develop's own notices name the card; ours name both


def last_text(d):
    return d["messages"][-1]["text"]


def test_a_basket_staged_by_the_server_keeps_the_focused_reply(auto):
    d = auto.turn(*CUSTOMER_PLAN_TURN)  # develop's design: the card shows the staged result
    assert baskets(d) and POINTER not in last_text(d) or CARD in last_text(d)
    assert last_text(d).startswith("Here is the plan.")


def test_a_basket_the_model_prepared_gets_one_pointer_when_the_reply_names_neither(
    auto, monkeypatch
):
    from aimo.config import settings

    monkeypatch.setattr(settings(), "cart_auto_prepare", False)  # the model-prepares flow
    d = auto.turn(
        "200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", plan())),
        tool_reply(call("prepare_order", prepared())), say("Done."),
    )  # fmt: skip
    assert baskets(d) and CARD in last_text(d) and last_text(d).count(POINTER) == 1


def test_a_reply_that_already_names_the_card_gets_nothing_added(auto, monkeypatch):
    from aimo.config import settings

    monkeypatch.setattr(settings(), "cart_auto_prepare", False)
    d = auto.turn(
        "200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", plan())),
        tool_reply(call("prepare_order", prepared())), say("Review the basket in Your order."),
    )  # fmt: skip
    assert baskets(d)
    assert "nothing is ordered until you press" not in last_text(d)


def test_a_denied_basket_made_by_the_model_points_to_the_card(auto, monkeypatch):
    from aimo.config import settings

    monkeypatch.setattr(settings(), "cart_auto_prepare", False)
    past = prepared() | {"delivery_date": str(date.today() - timedelta(days=1))}
    d = auto.turn(
        "200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", plan())),
        tool_reply(call("prepare_order", past)), say("I could not use that date."),
    )  # fmt: skip
    basket = baskets(d)[-1]
    assert basket["policy_outcome"] == "denied" and basket["order_id"] is None
    assert CARD in last_text(d)  # develop's own notice or ours: the card is named
