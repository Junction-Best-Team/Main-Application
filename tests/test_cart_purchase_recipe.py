# ruff: noqa: F811
"""The cart route for a SAVED RECIPE plan (the "request carbonara" flow: scale_recipe, match_ingredient).

The message only points at the saved plan; the server reloads it, so edited message text cannot change
what is bought. Existing rules stay: a recipe basket needs every ingredient matched (MEA-008), and the
plan revision binds the basket.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from test_recipes import (  # noqa: F401  (recipe fixtures and helpers)
    clean_recipes,
    import_fixture,
    match_all,
    meal_products,
    ref,
)

from aimo import auth, cart_purchase, conversations
from aimo.chat_schemas import CartPurchaseRequest, ConversationCreate
from aimo.db import Problem, connection, js
from aimo.recipe_schemas import MatchIngredient
from aimo.recipes import match_ingredient, scale_recipe


@pytest.fixture
def actor(buyer):
    return auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}


def conversation_pointing_at(buyer, plan_data):
    """A conversation whose latest assistant message carries the (display) plan, as the chat stores it."""
    cid = conversations.create(
        buyer, ConversationCreate(title="Carbonara", idempotency_key=str(uuid4()))
    )["id"]
    tid = uuid4()
    with connection() as c:
        c.execute(
            """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
            attempt,requested_by,worker_attempts,submitted_by)
            VALUES(%s,%s,%s,'x','complete',now(),%s,%s,0,%s)""",
            (tid, cid, str(uuid4()), uuid4(), buyer["id"], buyer["id"]),
        )
        c.execute(
            "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'user','carbonara')",
            (cid, tid),
        )
        c.execute(
            "INSERT INTO conversation_messages(conversation_id,turn_id,role,text,meal_plan) VALUES(%s,%s,'assistant','plan',%s)",
            (cid, tid, js(plan_data)),
        )
    return cid


def request(**over):
    return CartPurchaseRequest(
        delivery_date=date.today() + timedelta(days=2),
        destination="hotel-helsinki",
        request_id=str(uuid4()),
    ).model_copy(update=over)


def test_a_matched_recipe_plan_is_prepared_from_the_saved_plan(
    tmp_path, actor, buyer, service, meal_products
):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    cid = conversation_pointing_at(buyer, plan)
    out = cart_purchase.prepare_from_cart(buyer, cid, request(), service)
    lines = {i["product_id"]: i for i in out["proposal"]["snapshot"]["lines"]}
    assert set(lines) == {"recipe-spaghetti", "recipe-egg", "recipe-pepper"}
    assert lines["recipe-egg"]["quantity"]["requested_unit"] == "piece"
    assert lines["recipe-spaghetti"]["quantity"]["sales_quantity"] == "7"
    assert out["not_included"] == [] and out["proposal"]["order_id"] is None
    assert [p["proposal_id"] for p in conversations.detail(buyer, cid)["purchases"]] == [
        out["proposal"]["proposal_id"]
    ]


def test_edited_message_text_cannot_change_what_is_bought(
    tmp_path, actor, buyer, service, meal_products
):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    edited = {**plan, "ingredients": [dict(i, purchase_amount="9999") for i in plan["ingredients"]]}
    cid = conversation_pointing_at(buyer, edited)
    out = cart_purchase.prepare_from_cart(buyer, cid, request(), service)
    lines = {i["product_id"]: i for i in out["proposal"]["snapshot"]["lines"]}
    assert lines["recipe-spaghetti"]["quantity"]["sales_quantity"] == "7"  # the saved plan's number


def test_a_recipe_plan_with_an_unmatched_ingredient_is_refused_and_says_which(
    tmp_path, actor, buyer, service, meal_products
):
    *_, versions = import_fixture(tmp_path)
    plan = scale_recipe(actor, ref(versions))
    plan = match_ingredient(
        actor,
        MatchIngredient(
            plan_id=plan["recipe_plan_id"],
            revision=plan["recipe_plan_revision"],
            ingredient_id="spaghetti",
            product_id="recipe-spaghetti",
        ),
    )
    cid = conversation_pointing_at(buyer, plan)
    with pytest.raises(Problem) as error:
        cart_purchase.prepare_from_cart(buyer, cid, request(), service)
    assert error.value.code == "CART_INCOMPLETE" and error.value.status == 422
    assert set(error.value.details["unmatched"]) == {"Raw whole eggs", "Black pepper"}
    assert conversations.detail(buyer, cid)["purchases"] == []


def test_a_pointer_to_an_unknown_or_foreign_plan_is_refused(
    tmp_path, actor, buyer, service, meal_products
):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    cid = conversation_pointing_at(buyer, {**plan, "recipe_plan_id": str(uuid4())})
    with pytest.raises(Problem) as error:
        cart_purchase.prepare_from_cart(buyer, cid, request(), service)
    assert error.value.code == "CART_NOT_VERIFIED"


def test_a_product_withdrawn_since_matching_is_refused_closed(
    tmp_path, actor, buyer, service, meal_products
):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    cid = conversation_pointing_at(buyer, plan)
    with connection() as c:
        c.execute("DELETE FROM products WHERE id='recipe-egg'")
    with pytest.raises(Problem) as error:
        cart_purchase.prepare_from_cart(buyer, cid, request(), service)
    assert error.value.code == "CART_NOT_VERIFIED"
    assert conversations.detail(buyer, cid)["purchases"] == []


def test_replay_gives_the_same_recipe_proposal(tmp_path, actor, buyer, service, meal_products):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    cid = conversation_pointing_at(buyer, plan)
    same = request()
    first = cart_purchase.prepare_from_cart(buyer, cid, same, service)
    again = cart_purchase.prepare_from_cart(buyer, cid, same, service)
    assert again["proposal"]["proposal_id"] == first["proposal"]["proposal_id"]
    assert len(conversations.detail(buyer, cid)["purchases"]) == 1
