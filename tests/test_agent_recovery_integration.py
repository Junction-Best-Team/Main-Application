"""Real persisted worker flow with an authored provider interruption; no live calls."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from test_agent import call, reply

from aimo import agent, conversations
from aimo.agent_provider import AssistantReply
from aimo.chat_schemas import ConversationCreate, MessageRequest
from aimo.db import Problem, connection


def test_timeout_saves_partial_plan_and_next_turn_can_continue(monkeypatch, buyer, service):
    config = SimpleNamespace(llm_max_tool_rounds=12, llm_model="scripted")
    monkeypatch.setattr(agent, "settings", lambda: config)
    basis = {
        "title": "Authored tomato pasta estimate",
        "base_servings": 4,
        "portions": 200,
        "ingredients": [
            {"name": "Dry pasta", "amount": "400", "unit": "g"},
            {"name": "Tomato sauce", "amount": "600", "unit": "ml"},
        ],
    }
    script = iter(
        [
            reply(call("draft_recipe", basis)),
            Problem("LLM_TIMEOUT", "synthetic timeout", 504),
            reply(text="The saved estimate still needs product matches."),
        ]
    )
    seen = []

    def complete(history, tools, deadline):
        seen.append(deepcopy(history))
        result = next(script)
        if isinstance(result, Exception):
            raise result
        return AssistantReply.model_validate(result)

    monkeypatch.setattr(agent, "chat_provider", lambda *_: SimpleNamespace(complete=complete))
    cid = conversations.create(
        buyer, ConversationCreate(title="Pasta", idempotency_key=str(uuid4()))
    )["id"]
    result = conversations.message(
        buyer, cid, MessageRequest(text="Pasta for 200", idempotency_key=str(uuid4())), service
    )
    assert result["retry_message"] is None and not result["busy"]
    saved = result["messages"][-1]
    assert saved["notice"] is None and "time limit" in saved["text"]
    assert [i["amount"] for i in saved["meal_plan"]["ingredients"]] == ["20", "30"]
    assert saved["proposal_id"] is None
    with connection() as c:
        assert c.execute("SELECT state FROM conversation_turns").fetchone()["state"] == "complete"
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
    conversations.message(
        buyer, cid, MessageRequest(text="Continue", idempotency_key=str(uuid4())), service
    )
    assert "Stored meal plan:" in seen[-1][-2]["content"]
    assert "Authored tomato pasta estimate" in seen[-1][-2]["content"]


def test_timeout_preserves_partial_cart_and_existing_auto_prepare_without_ordering(
    monkeypatch, buyer, service
):
    from aimo.config import settings

    monkeypatch.setattr(settings(), "cart_auto_prepare", True)
    monkeypatch.setattr(
        agent, "settings", lambda: SimpleNamespace(llm_max_tool_rounds=12, llm_model="scripted")
    )
    plan = {
        "title": "Milk and cheese",
        "portions": 1,
        "ingredients": [
            {"name": "Milk", "amount": "10", "unit": "L", "product_id": "464306"},
            {"name": "Cheese", "amount": "1", "unit": "KG"},
        ],
    }
    script = iter(
        [
            reply(call("get_product", {"product_id": "464306"}), call("publish_meal_plan", plan)),
            Problem("LLM_TIMEOUT", "synthetic timeout", 504),
        ]
    )

    def complete(*_):
        result = next(script)
        if isinstance(result, Exception):
            raise result
        return AssistantReply.model_validate(result)

    monkeypatch.setattr(agent, "chat_provider", lambda *_: SimpleNamespace(complete=complete))
    cid = conversations.create(
        buyer, ConversationCreate(title="Milk", idempotency_key=str(uuid4()))
    )["id"]
    result = conversations.message(
        buyer, cid, MessageRequest(text="Milk and cheese", idempotency_key=str(uuid4())), service
    )
    saved = result["messages"][-1]
    assert saved["proposal_id"] and len(saved["meal_plan"]["ingredients"]) == 2
    assert "1 ingredient still needs a catalog match" in saved["text"]
    assert result["retry_message"] is None
    assert result["purchases"][0]["snapshot"]["mode"] == "fixture"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 0


def test_incomplete_seasonings_fall_back_before_saved_plan_selection(
    monkeypatch, tmp_path, buyer, service
):
    from test_agent_recipe_planning import estimate, incomplete_carbonara
    from test_recipes import import_fixture, source_recipe

    from aimo.config import settings

    monkeypatch.setattr(settings(), "cart_auto_prepare", False)
    monkeypatch.setattr(
        agent, "settings", lambda: SimpleNamespace(llm_max_tool_rounds=12, llm_model="scripted")
    )
    raw = source_recipe()
    basis = incomplete_carbonara()["recipe"]
    raw["baseServings"] = basis["base_servings"]
    raw["ingredients"] = [
        {"id": i["id"], "name": {"en": i["name"]}, "quantity": i["quantity"],
         "unit": i["unit"], "scaling": i["scaling"]}
        for i in basis["ingredients"]
    ]
    *_, versions = import_fixture(tmp_path, [raw])
    reference = dict(versions[0])
    script = iter([
        reply(call("get_recipe", reference)),
        reply(call("scale_recipe", reference | {"portions": 200})),
        reply(call("draft_recipe", estimate())),
        reply(text="I planned an estimate for 200 portions, including estimated salt and pepper."),
    ])
    seen = []

    def complete(history, *_):
        seen.append(deepcopy(history))
        return AssistantReply.model_validate(next(script))

    def unexpected_policy(*_):
        raise AssertionError("Recipe planning should not read purchasing policy")

    monkeypatch.setattr(service, "get_purchase_policy", unexpected_policy)
    monkeypatch.setattr(agent, "chat_provider", lambda *_: SimpleNamespace(complete=complete))
    cid = conversations.create(
        buyer, ConversationCreate(title="Carbonara", idempotency_key=str(uuid4()))
    )["id"]
    result = conversations.message(
        buyer, cid, MessageRequest(text="i want to sell 200 carbonara", idempotency_key=str(uuid4())), service
    )
    assert len(seen) == 4 and not result["busy"] and result["retry_message"] is None
    message = result["messages"][-1]
    plan = message["meal_plan"]
    assert plan["recipe_plan_id"] is None and plan["portions"] == 200
    assert {i["name"]: i["amount"] for i in plan["ingredients"]} == {
        "Spaghetti": "20", "Guanciale": "10", "Egg yolks": "300", "Whole egg": "100",
        "Pecorino romano": "6", "Black pepper": "0.1", "Salt for the water": "2",
    }
    assert "Assistant-drafted recipe estimate" in plan["notes"][0]
    with connection() as c:
        assert c.execute(
            "SELECT count(*) AS n FROM recipe_plans rp JOIN conversation_turns t ON t.id::text=rp.turn_id "
            "WHERE t.conversation_id=%s", (cid,),
        ).fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 0
