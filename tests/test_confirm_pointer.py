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


def last_text(d):
    return d["messages"][-1]["text"]


def test_an_open_basket_from_the_server_points_to_the_button_once(auto):
    d = auto.turn(*CUSTOMER_PLAN_TURN)
    assert baskets(d) and last_text(d).count(POINTER) == 1


def test_a_denied_basket_made_by_the_model_still_points_to_the_card(auto):
    past = prepared() | {"delivery_date": str(date.today() - timedelta(days=1))}
    d = auto.turn(
        "200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", plan())),
        tool_reply(call("prepare_order", past)), say("I could not use that date."),
    )  # fmt: skip
    basket = baskets(d)[-1]
    assert basket["policy_outcome"] == "denied" and basket["order_id"] is None
    assert POINTER in last_text(
        d
    )  # tells the customer where the basket is and that it is not ready


def test_a_basket_the_budget_blocks_points_to_the_card_too(auto):
    from uuid import uuid4

    from aimo.worker import run_once

    cid = auto.turn.cid
    auto.client.post(
        f"/api/conversations/{cid}/messages", headers=auto.headers,
        json={"text": "200 portions of carbonara", "idempotency_key": str(uuid4()),
              "constraints": {"budget_gross": "5"}},
    )  # fmt: skip
    auto.script.extend([*MATCH, tool_reply(call("publish_meal_plan", plan())), say("Plan ready.")])
    assert run_once(auto.service)
    d = auto.client.get(f"/api/conversations/{cid}").json()
    assert baskets(d) and POINTER in last_text(d)
