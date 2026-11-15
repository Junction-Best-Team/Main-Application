"""A customer can always reach the purchase panel (owner: "the purchase button should always be there").

A scripted provider replays REAL model sequences through the real worker and tools: recipe, product
matching (the draft cart updates), then prepare_order or not, and the customer's "yes, make the order".
The browser shows the display-only Draft cart whenever `draft_cart` exists, no basket is selected and no
`purchases` entry has `proposal_id == draft_cart.proposal_id` (StagedOverview.tsx). `shows_draft_panel`
mirrors that rule: whenever a basket exists for the conversation it must be False.
"""

import json
import os
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from aimo import agent as internal
from aimo import fixtures
from aimo.api import create_app
from aimo.config import settings
from aimo.db import fingerprint
from aimo.ingest import publish
from aimo.service import Service
from aimo.upstream import FixtureClient
from aimo.worker import run_once

NAMES = ["pasta", "eggs", "pork", "cheese", "pepper"]
AMOUNTS = ["20", "12", "6", "4", "0.2"]


def call(name, arguments):
    return {
        "id": str(uuid4()),
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def tool_reply(*calls):
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def say(text):
    return {"role": "assistant", "content": text}


def plan():
    return {
        "title": "Traditional carbonara",
        "portions": 200,
        "base_servings": 4,
        "ingredients": [
            {"name": n, "amount": a, "unit": "KG", "product_id": "meal-" + n}
            for n, a in zip(NAMES, AMOUNTS)
        ],
        "notes": ["Authored recipe estimate."],
    }


def prepared():
    return {
        "request_id": "200 portions carbonara",
        "destination": "hotel-helsinki",
        "delivery_date": str(date.today() + timedelta(days=2)),
        "budget_gross": "1000",
        "requirements": {},
        "lines": [
            {"product_id": "meal-" + n, "amount": a, "unit": "KG"} for n, a in zip(NAMES, AMOUNTS)
        ],
    }


MATCH = [
    tool_reply(*[call("search_products", {"query": n}) for n in NAMES]),
    tool_reply(*[call("get_product", {"product_id": "meal-" + n}) for n in NAMES]),
]


@pytest.fixture
def chat(monkeypatch, buyer):
    original = fixtures.fixture_facts()
    products = []
    for n in NAMES:
        p = deepcopy(original[0])
        p.update(
            id="meal-" + n, name="Authored carbonara " + n, names={"en": "Authored carbonara " + n},
            sales_unit="KG", base_unit="KG", units={"KG": "1"}, order_step="0.01",
            variable_weight=False, claims=[], allergens={},
            measures={"KG": {"value": "1", "status": "known", "basis": ["authored.fixture"]},
                      "L": {"value": None, "status": "unknown", "basis": []}},
            provenance={"source": "authored meal fixture", "product_id": "meal-" + n},
        )  # fmt: skip
        products.append(p)
    monkeypatch.setattr(fixtures, "fixture_facts", lambda: original + products)
    publish(original + products, "authored-draft-cart-test", fingerprint(original + products))
    config = SimpleNamespace(
        llm_api_key="unused-scripted-provider", llm_base_url="https://unused.test",
        llm_model="scripted", llm_timeout_seconds=20, llm_max_tool_rounds=20,
    )  # fmt: skip
    monkeypatch.setattr(internal, "settings", lambda: config)
    # These tests are about the model path; test_cart_auto_prepare.py turns the auto-prepare on.
    monkeypatch.setattr(settings(), "cart_auto_prepare", False)
    script = []

    def provider(request):
        return httpx.Response(200, json={"choices": [{"message": script.pop(0)}]})

    real = httpx.Client
    monkeypatch.setattr(
        internal.httpx, "Client",
        lambda **kw: real(transport=httpx.MockTransport(provider), **kw),
    )  # fmt: skip
    service = Service(FixtureClient())
    with TestClient(create_app(service)) as client:
        signed = client.post(
            "/api/login", headers={"Origin": "http://testserver"},
            json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
        )  # fmt: skip
        headers = {"Origin": "http://testserver", "X-CSRF-Token": signed.json()["csrf_token"]}

        def conversation():
            cid = client.post(
                "/api/conversations", headers=headers,
                json={"title": "Carbonara", "idempotency_key": str(uuid4())},
            ).json()["id"]  # fmt: skip

            def turn(text, *replies):
                """The customer writes `text`; the model answers with `replies` (one provider call each)."""
                script.extend(replies)
                sent = client.post(
                    f"/api/conversations/{cid}/messages", headers=headers,
                    json={"text": text, "idempotency_key": str(uuid4())},
                )  # fmt: skip
                assert sent.status_code == 200, sent.text
                assert run_once(service)
                assert not list(script), "the scripted sequence was not fully used"
                return client.get(f"/api/conversations/{cid}").json()

            turn.cid = cid
            return turn

        yield SimpleNamespace(
            turn=conversation(), new_conversation=conversation, client=client, headers=headers,
            service=service, script=script
        )


def shows_draft_panel(data):
    """StagedOverview.tsx: DraftCartPanel when a draft exists and no purchase carries its proposal."""
    draft = data["draft_cart"]
    return bool(draft) and not any(
        p["proposal_id"] == draft["proposal_id"] for p in data["purchases"]
    )


def test_a_basket_prepared_in_the_same_turn_shows_the_purchase_panel(chat):
    data = chat.turn(
        "200 portions of carbonara, hotel-helsinki, 1000 EUR",
        tool_reply(call("draft_recipe", {
            "title": "Traditional carbonara", "base_servings": 4, "portions": 200,
            "ingredients": [{"name": n, "amount": a, "unit": "kg"}
                            for n, a in zip(NAMES, ["0.4", "0.24", "0.12", "0.08", "0.004"])],
        })),
        *MATCH,
        tool_reply(call("publish_meal_plan", plan())),
        tool_reply(call("prepare_order", prepared())),
        say("Review the basket and confirm in the product."),
    )  # fmt: skip
    assert len(data["purchases"]) == 1
    assert not shows_draft_panel(data), data["draft_cart"]


def test_a_plan_without_a_prepared_basket_then_yes_make_the_order_shows_the_purchase_panel(chat):
    first = chat.turn(
        "200 portions of carbonara, hotel-helsinki, 1000 EUR",
        tool_reply(call("draft_recipe", {
            "title": "Traditional carbonara", "base_servings": 4, "portions": 200,
            "ingredients": [{"name": n, "amount": a, "unit": "kg"}
                            for n, a in zip(NAMES, ["0.4", "0.24", "0.12", "0.08", "0.004"])],
        })),
        *MATCH,
        tool_reply(call("publish_meal_plan", plan())),
        say("Here is the plan. Shall I prepare the order?"),
    )  # fmt: skip
    assert (
        first["purchases"] == [] and first["draft_cart"] is not None
    )  # a draft: nothing to buy yet
    second = chat.turn(
        "yes, make the order",
        tool_reply(call("prepare_order", prepared())),
        say("Review the basket and confirm in the product."),
    )  # fmt: skip
    assert len(second["purchases"]) == 1
    assert not shows_draft_panel(second), second["draft_cart"]


def test_the_basket_made_in_the_second_turn_with_a_republished_plan_also_shows_it(chat):
    chat.turn(
        "200 portions of carbonara",
        *MATCH,
        tool_reply(call("publish_meal_plan", plan())),
        say("Here is the plan. Shall I prepare the order?"),
    )
    second = chat.turn(
        "yes, make the order",
        *MATCH,
        tool_reply(call("publish_meal_plan", plan())),
        tool_reply(call("prepare_order", prepared())),
        say("Review the basket and confirm in the product."),
    )
    assert len(second["purchases"]) == 1
    assert not shows_draft_panel(second), second["draft_cart"]


def test_a_later_text_only_turn_keeps_the_purchase_panel(chat):
    chat.turn(
        "200 portions of carbonara",
        *MATCH,
        tool_reply(call("publish_meal_plan", plan())),
        tool_reply(call("prepare_order", prepared())),
        say("Review the basket and confirm in the product."),
    )
    later = chat.turn("thanks, what is the delivery date?", say("Delivery is in two days."))
    assert len(later["purchases"]) == 1
    assert not shows_draft_panel(later), later["draft_cart"]


# --- option 1: the plan the customer already saw is restored in the next turn ----------------------

CUSTOMER_PLAN_TURN = (
    "200 portions of carbonara, hotel-helsinki, 1000 EUR",
    *MATCH,
    tool_reply(call("publish_meal_plan", plan())),
    say("Here is the plan. Shall I prepare the order?"),
)
YES = ("yes, make the order",)


def prepare_only():
    return (tool_reply(call("prepare_order", prepared())), say("Review the basket and confirm."))


def test_yes_prepares_the_basket_from_the_plan_the_customer_saw(chat):
    first = chat.turn(*CUSTOMER_PLAN_TURN)
    assert first["purchases"] == [] and first["draft_cart"] is not None
    second = chat.turn(*YES, *prepare_only())  # no new search, no new get_product, no new plan
    assert len(second["purchases"]) == 1 and not shows_draft_panel(second)
    assert {i["product_id"] for i in second["purchases"][0]["snapshot"]["lines"]} == {
        "meal-" + n for n in NAMES
    }


def test_nothing_is_restored_into_another_conversation(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    other = chat.new_conversation()
    data = other(*YES, *prepare_only())  # this chat never had a plan
    assert data["purchases"] == [] and data["draft_cart"] is None


def test_nothing_is_restored_once_a_basket_was_prepared_after_the_plan(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    chat.turn(*YES, *prepare_only())
    third = chat.turn("prepare it again", *prepare_only())  # the old plan is not offered again
    assert len(third["purchases"]) == 1  # still the one basket; the second prepare was refused


def test_a_plan_that_a_later_text_answer_has_moved_past_is_not_restored(chat):
    chat.turn(*CUSTOMER_PLAN_TURN)
    chat.turn("use goat cheese instead", say("Do you want me to swap the cheese?"))
    third = chat.turn("yes", *prepare_only())
    assert third["purchases"] == []  # the stored plan is no longer the latest answer


def test_a_product_withdrawn_since_is_not_restored_and_the_draft_stays(chat):
    from aimo.db import connection

    chat.turn(*CUSTOMER_PLAN_TURN)
    with connection() as c:  # the supplier withdrew one product after the plan was shown
        c.execute(
            "UPDATE products SET facts=jsonb_set(facts,'{deleted}','true') WHERE id='meal-eggs'"
        )
    second = chat.turn(*YES, *prepare_only())
    assert second["purchases"] == [] and second["draft_cart"] is not None


def test_a_product_that_left_the_catalog_is_not_restored(chat):
    from aimo.db import connection

    chat.turn(*CUSTOMER_PLAN_TURN)
    with connection() as c:
        c.execute("DELETE FROM products WHERE id='meal-pork'")
    second = chat.turn(*YES, *prepare_only())
    assert second["purchases"] == [] and second["draft_cart"] is not None


def test_restored_products_are_verified_only_for_the_plan_they_came_from(chat, service, buyer):
    from aimo import auth
    from aimo.agent_tools import ToolSession
    from aimo.db import Problem

    session = ToolSession(auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}, service)
    assert session.restore_plan(plan()) is True
    assert set(session.products) == {"meal-" + n for n in NAMES} and session.plan is not None
    wider = plan() | {
        "ingredients": plan()["ingredients"]
        + [{"name": "salt", "amount": "1", "unit": "KG", "product_id": "464306"}]
    }
    from aimo.chat_schemas import MealPlan

    class Input(MealPlan):
        pass

    with pytest.raises(Problem) as refused:
        session.publish(Input.model_validate(wider))
    assert refused.value.code in ("PRODUCT_NOT_VERIFIED", "INCOMPLETE_MEAL_PLAN")


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: p | {"ingredients": p["ingredients"] * 100},  # oversized: 500 ingredients
        lambda p: p | {"ingredients": [dict(p["ingredients"][0], amount="-1")]},
        lambda p: p | {"recipe_plan_id": str(uuid4()), "recipe_plan_revision": 1},
        lambda p: p | {"unexpected": "field"},
        lambda p: "not a plan",
    ],
)
def test_a_tampered_or_oversized_stored_plan_is_rejected(chat, service, buyer, tamper):
    from aimo import auth
    from aimo.agent_tools import ToolSession

    session = ToolSession(auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}, service)
    assert session.restore_plan(tamper(plan())) is False
    assert session.plan is None and session.products == {}


def test_the_selection_rule_picks_only_the_latest_unprepared_complete_plan():
    from aimo.conversations import restorable_plan

    mp = plan()
    user = {"role": "user", "text": "x", "meal_plan": None, "proposal_id": None, "notice": None}
    reply = user | {"role": "assistant"}
    with_plan = reply | {"meal_plan": mp}
    assert restorable_plan([user, with_plan, user]) == mp
    assert restorable_plan([user, with_plan, reply, user]) is None  # a later answer moved past it
    assert restorable_plan([user, with_plan, reply | {"proposal_id": "p"}, user]) is None
    assert restorable_plan([user, with_plan, user | {"proposal_id": "p"}]) is None
    assert (
        restorable_plan([user, with_plan, reply | {"notice": "provider_unavailable"}, user]) == mp
    )
    assert restorable_plan([user, reply | {"meal_plan": mp | {"recipe_plan_id": "r"}}]) is None
    unmatched = mp | {"ingredients": [dict(mp["ingredients"][0], product_id=None)]}
    assert restorable_plan([user, reply | {"meal_plan": unmatched}]) == unmatched  # partly matched
    assert restorable_plan([user]) is None and restorable_plan([]) is None


# --- a plan that is only partly matched is restored too (verified for its matched ids only) -----------


def partial_plan(unmatched=("pepper",)):
    p = plan()
    for item in p["ingredients"]:
        if item["name"] in unmatched:
            item["product_id"] = None
    return p


def test_a_partly_matched_plan_is_restored_verified_for_its_matched_products_only(
    chat, service, buyer
):
    from aimo import auth
    from aimo.agent_tools import ToolSession

    session = ToolSession(auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}, service)
    assert session.restore_plan(partial_plan()) is True
    assert set(session.products) == {"meal-" + n for n in NAMES if n != "pepper"}
    assert [i.product_id for i in session.plan.ingredients][-1] is None  # still unmatched


def test_the_unmatched_item_is_not_bought_and_no_basket_appears(chat):
    first = chat.turn(
        "200 portions of carbonara", *MATCH,
        tool_reply(call("publish_meal_plan", partial_plan())), say("Pepper still needs a product."),
    )  # fmt: skip
    assert first["draft_cart"] is not None
    # "yes, order it": the model tries to prepare what the plan holds; pepper has no product yet
    second = chat.turn("yes, order it", *prepare_only())
    assert second["purchases"] == [] and shows_draft_panel(second)


def test_the_model_finishes_the_matching_and_prepares_in_the_turn_after_a_partial_plan(chat):
    chat.turn(
        "200 portions of carbonara", *MATCH,
        tool_reply(call("publish_meal_plan", partial_plan())), say("Pepper still needs a product."),
    )  # fmt: skip
    only_pepper = [
        tool_reply(call("search_products", {"query": "pepper"})),
        tool_reply(call("get_product", {"product_id": "meal-pepper"})),
    ]
    finished = chat.turn(
        "yes, order it", *only_pepper,  # the four matched products are NOT searched or read again
        tool_reply(call("publish_meal_plan", plan())), *prepare_only(),
    )  # fmt: skip
    assert len(finished["purchases"]) == 1 and not shows_draft_panel(finished)
    assert len(finished["purchases"][0]["snapshot"]["lines"]) == 5


def test_a_withdrawn_matched_product_stops_a_partial_restore_too(chat):
    from aimo.db import connection

    chat.turn(
        "200 portions of carbonara", *MATCH,
        tool_reply(call("publish_meal_plan", partial_plan())), say("Pepper still needs a product."),
    )  # fmt: skip
    with connection() as c:
        c.execute("DELETE FROM products WHERE id='meal-pork'")
    only_pepper = [
        tool_reply(call("search_products", {"query": "pepper"})),
        tool_reply(call("get_product", {"product_id": "meal-pepper"})),
    ]
    data = chat.turn("yes, order it", *only_pepper, tool_reply(call("publish_meal_plan", plan())),
                     *prepare_only())  # fmt: skip
    assert data["purchases"] == []  # pork is no longer verified, so the plan cannot be published
