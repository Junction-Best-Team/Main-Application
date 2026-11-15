# ruff: noqa: F811
"""A basket the SERVER makes (cart route, PUT, auto-prepare) builds its label from the plan title: a title that
claims a status ("Order confirmed and paid") gets a neutral label instead of failing the cart (8c round 2)."""

from test_cart_auto_prepare import auto, baskets  # noqa: F401
from test_draft_cart_purchase import MATCH, call, chat, plan, say, tool_reply  # noqa: F401


def label_of(auto, title):
    d = auto.turn(
        "200 portions of carbonara", *MATCH,
        tool_reply(call("publish_meal_plan", plan() | {"title": title})), say("Plan."),
    )  # fmt: skip
    return baskets(d)[0]["request"]["request_id"]


def test_a_claiming_title_gets_a_neutral_label(auto):
    assert label_of(auto, "Order confirmed and paid carbonara") == "Cart"


def test_a_normal_title_keeps_its_name(auto):
    assert label_of(auto, "Traditional carbonara") == "Cart: Traditional carbonara"
