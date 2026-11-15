# ruff: noqa: F811
"""The phases through the real worker, routes and database: no plan-only mode, two layers of backstop.

A shopping request that the model stops at the plan ends with the basket on the card: first the phase
continuation asks the model to prepare (one extra model reply); if the model still does not, the server's
auto-prepare makes the basket from the stored plan.
"""

from test_cart_auto_prepare import auto, baskets, state  # noqa: F401
from test_draft_cart_purchase import (  # noqa: F401
    MATCH,
    call,
    chat,
    plan,
    prepared,
    say,
    shows_draft_panel,
    tool_reply,
)

from aimo.config import settings

BRIEF = {
    "intent": "build_list",
    "goal": "carbonara for 200",
    "starting_point": "dish",
    "portions": 200,
    "missing_facts": [],
}


def shopping(auto, monkeypatch, *replies):
    monkeypatch.setattr(settings(), "agent_phases", True)
    return auto.turn(
        "ingredients for 200 portions of carbonara",
        tool_reply(
            call("record_request", BRIEF)
        ),  # develop's request brief comes first in a conversation
        *MATCH,
        tool_reply(call("publish_meal_plan", plan())),
        *replies,
    )


def test_a_model_that_stops_at_the_plan_is_continued_and_prepares(auto, monkeypatch):
    # The model-prepares flow: automatic cart preparation is off (with it on the server stages the basket).
    monkeypatch.setattr(settings(), "cart_auto_prepare", False)
    d = shopping(
        auto,
        monkeypatch,
        say("Here is the plan."),  # stops short: no buy word, no date asked
        tool_reply(call("prepare_order", prepared())),
        say("The basket is prepared; press Confirm purchase."),
    )
    assert len(baskets(d)) == 1 and not shows_draft_panel(d)
    assert d["messages"][-1]["text"].startswith("The basket is prepared")


def test_with_automatic_preparation_the_server_stages_the_basket_after_the_reply(auto, monkeypatch):
    # No model nudge here: the phase says the server prepares; the cart backstop makes the basket.
    d = shopping(auto, monkeypatch, say("Here is the plan."))
    assert len(baskets(d)) == 1 and state(baskets(d)[0]) != "cancelled"  # auto-prepare backstop
    assert not shows_draft_panel(d)
