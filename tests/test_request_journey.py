# ruff: noqa: F811
"""Multi-turn request journeys through the worker, with explicit authored provider/commerce fixtures."""

from decimal import Decimal

import pytest
from test_cart_auto_prepare import auto, baskets, data  # noqa: F401
from test_draft_cart_purchase import MATCH, call, chat, plan, say, tool_reply  # noqa: F401

from aimo import request_brief
from aimo.db import connection
from aimo.google_chat import GoogleChatProvider


def brief(**changes):
    return {
        "intent": "build_list",
        "goal": "Carbonara for 200 people",
        "starting_point": "dish",
        "portions": 200,
        "budget_gross": "1000",
        **changes,
    }


def remembered(chat):
    with connection() as c:
        return request_brief.load(c, chat.turn.cid)


def build(chat, **changes):
    return chat.turn(
        "Carbonara for 200 people, maximum 1000 euros.",
        tool_reply(call("record_request", brief(**changes))),
        *MATCH,
        tool_reply(call("publish_meal_plan", plan())),
        say("Here is the carbonara plan."),
    )


def test_idea_becomes_a_chosen_meal_then_resizes_without_losing_the_budget(auto):
    first = auto.turn(
        "I need an affordable team lunch but have no idea what to serve.",
        tool_reply(
            call(
                "record_request",
                brief(
                    intent="explore",
                    goal="Affordable team lunch",
                    portions=None,
                    starting_point="idea",
                    budget_gross=None,
                    missing_facts=["Choose a meal and number of portions"],
                ),
            )
        ),
        say("Would you prefer a pasta dish or soup?"),
    )
    assert not baskets(first) and not first["draft_cart"]
    assert remembered(auto).intent == "explore"
    chosen = build(auto)
    old = baskets(chosen)[0]
    assert Decimal(old["request"]["budget_gross"]) == 1000
    previous_calls = len(auto.seen)
    revised = auto.turn(
        "Actually make that 150 people, same budget.",
        tool_reply(call("record_request", brief(portions=150, goal="Carbonara for 150 people"))),
        tool_reply(call("resize_plan", {"portions": 150})),
        say("Adjusted to 150 portions."),
    )
    _, native_history = GoogleChatProvider.contents(auto.seen[previous_calls])
    assert native_history[-1]["role"] == "user"
    assert "Actually make that 150 people" in native_history[-1]["parts"][-1]["text"]
    assert "Persisted purchasing state" in native_history[-2]["parts"][-1]["text"]
    current = next(
        b for b in baskets(revised) if b["proposal_id"] == revised["messages"][-1]["proposal_id"]
    )
    assert current["proposal_id"] != old["proposal_id"]
    assert Decimal(current["request"]["budget_gross"]) == 1000
    assert {i["product_id"]: Decimal(i["amount"]) for i in current["request"]["lines"]}[
        "meal-pasta"
    ] == 15
    assert remembered(auto).portions == 150
    assert (
        next(b for b in baskets(revised) if b["proposal_id"] == old["proposal_id"])[
            "approval_status"
        ]
        == "cancelled"
    )
    assert "Persisted request understanding" in auto.seen[-1][0]["content"]
    assert not any(b["order_id"] for b in baskets(revised))


def test_exploring_a_different_idea_does_not_replace_an_existing_basket(auto):
    old = baskets(build(auto))[0]
    exploring = auto.turn(
        "Before deciding, what about a soup instead?",
        tool_reply(
            call("record_request", brief(intent="explore", goal="Compare soup with carbonara"))
        ),
        # A premature plan publication is refused, even if a model tries it.
        tool_reply(call("publish_meal_plan", plan())),
        say("A soup could be simpler to serve."),
    )
    assert len(baskets(exploring)) == 1
    assert baskets(exploring)[0]["proposal_id"] == old["proposal_id"]
    assert baskets(exploring)[0]["approval_status"] != "cancelled"


@pytest.mark.parametrize(
    "requirements",
    [
        {"unsupported": ["vegan"]},
        {"milk_free": True},
        {"free_from": ["AE"]},
    ],
)
def test_chat_requirements_reach_background_preparation_without_structured_toggles(
    auto, requirements
):
    d = build(auto, requirements=requirements)
    basket = baskets(d)[0]
    for key, value in requirements.items():
        assert basket["request"]["requirements"][key] == value
    assert basket["policy_outcome"] in ("denied", "needs_resolution")
    assert not basket["order_id"]
    assert remembered(auto).requirements.model_dump()[next(iter(requirements))] == next(
        iter(requirements.values())
    )


def test_a_lower_chat_budget_blocks_an_oversized_basket(auto):
    d = build(auto, budget_gross="1")
    assert Decimal(baskets(d)[0]["request"]["budget_gross"]) == 1
    assert baskets(d)[0]["policy_outcome"] == "denied"


def test_replacing_an_ingredient_preserves_unaffected_matches(auto):
    build(auto)
    recipe = {
        "title": "Mushroom carbonara",
        "base_servings": 200,
        "portions": 200,
        "ingredients": [
            {
                "name": "mushrooms" if i["name"] == "pork" else i["name"],
                "amount": i["amount"],
                "unit": "kg",
            }
            for i in plan()["ingredients"]
        ],
        "estimated_ingredients": ["mushrooms"],
    }
    d = auto.turn(
        "Replace the pork with mushrooms; keep the other ingredients and quantities.",
        tool_reply(call("record_request", brief(goal="Mushroom carbonara for 200 people"))),
        tool_reply(call("revise_recipe", recipe)),
        say("I replaced the pork; mushrooms still need a product match."),
    )
    ingredients = d["messages"][-1]["meal_plan"]["ingredients"]
    assert next(i for i in ingredients if i["name"] == "mushrooms")["product_id"] is None
    assert {i["product_id"] for i in ingredients if i["name"] != "mushrooms"} == {
        "meal-pasta",
        "meal-eggs",
        "meal-cheese",
        "meal-pepper",
    }
    assert remembered(auto).budget_gross == 1000


def test_a_background_failure_explains_recovery_and_preserves_the_draft(auto, monkeypatch):
    from aimo.db import Problem

    def unavailable(*args, **kwargs):
        raise Problem("UPSTREAM_UNAVAILABLE", "private diagnostic", 503)

    monkeypatch.setattr(auto.service, "prepare_order", unavailable)
    d = build(auto)
    assert not baskets(d) and d["draft_cart"]
    assert "couldn’t finish checking the basket" in d["messages"][-1]["text"]
    assert "private diagnostic" not in d["messages"][-1]["text"]
    assert remembered(auto).budget_gross == 1000


def test_request_writes_are_fenced_to_the_author_buyer_and_running_attempt(auto, buyer):
    from aimo.db import Problem

    build(auto)
    with connection() as c:
        turn = c.execute(
            "SELECT * FROM conversation_turns WHERE conversation_id=%s ORDER BY created_at DESC LIMIT 1",
            (auto.turn.cid,),
        ).fetchone()
    identity = {
        "buyer_id": buyer["buyer_id"],
        "_conversation_id": auto.turn.cid,
        "_turn_id": str(turn["id"]),
        "_attempt": str(turn["attempt"]),
        "_requested_by": buyer["id"],
    }
    for actor in (identity, identity | {"buyer_id": "different-buyer"}):
        with pytest.raises(Problem) as error:
            request_brief.save(
                actor, request_brief.RequestBrief.model_validate(brief(budget_gross="10000"))
            )
        assert error.value.code == "TURN_REPLACED"
    assert remembered(auto).budget_gross == 1000
