"""Opt-in real-model journeys; isolated fixture catalog/prices, never live supplier calls.

Run with AIMO_LIVE_JOURNEYS=1 AIMO_EVAL_ENV_FILE=/private/path/.env and TEST_DATABASE_URL.
The private env file supplies only the Google key/model; no credentials are printed.
"""

import json
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from supplier_fixture import FixtureClient

from aimo import conversations, request_brief
from aimo.chat_schemas import ConversationCreate, MessageRequest
from aimo.config import settings
from aimo.db import connection
from aimo.guardrails import Guardrails
from aimo.service import Service

pytestmark = pytest.mark.skipif(
    os.getenv("AIMO_LIVE_JOURNEYS") != "1", reason="Opt-in real Google model evaluation only"
)


@pytest.fixture
def live(monkeypatch, buyer):
    values = dotenv_values(os.environ["AIMO_EVAL_ENV_FILE"])
    if not values.get("GEMINI_API_KEY"):
        pytest.skip("The private env file has no Google key")
    cfg = settings()
    monkeypatch.setattr(cfg, "gemini_api_key", values["GEMINI_API_KEY"])
    monkeypatch.setattr(cfg, "llm_provider", "google")
    monkeypatch.setattr(cfg, "guardrail_provider", "google")
    monkeypatch.setattr(cfg, "guardrail_mode", "enforce")
    monkeypatch.setattr(cfg, "llm_model", values.get("LLM_MODEL") or "gemini-4-carbon")
    monkeypatch.setattr(cfg, "cart_auto_prepare", True)
    service = Service(FixtureClient())
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    reviews = []
    review_output = Guardrails.review_output

    def reviewed(guard, session, narrative, tool_log):
        text = review_output(guard, session, narrative, tool_log)
        result = guard.records[-1]
        reviews.append(
            {
                "reply": narrative,
                "failed": result.failed,
                "uncertain": result.uncertain,
                "error": result.error,
            }
        )
        return text

    monkeypatch.setattr(Guardrails, "review_output", reviewed)

    def turn(text):
        result = conversations.message(
            buyer, cid, MessageRequest(text=text, idempotency_key=str(uuid4())), service
        )
        with connection() as c:
            brief = request_brief.load(c, cid)
            assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
        assert brief is not None, "The model did not persist its understanding"
        assert len(result["messages"][-1]["text"]) < 800
        result["evaluation_reviews"] = reviews
        return result, brief

    return turn


def test_live_idea_to_customer_recipe_to_revised_quantities(live):
    result, brief = live(
        "I need to feed a team but haven't chosen anything. Help me compare options first; "
        "don't build the shopping list yet."
    )
    assert brief.intent == "explore" and not result["purchases"]
    result, brief = live(
        "Let's make warm milk for 20 people. Use my recipe: 0.5 litres of milk for 2 people, "
        "no other ingredients. Build the product list, maximum 100 euros."
    )
    assert brief.starting_point == "customer_recipe" and brief.portions == 20
    assert brief.budget_gross == 100
    plans = [m["meal_plan"] for m in result["messages"] if m["meal_plan"]]
    if not plans:
        pytest.fail(json.dumps(result["evaluation_reviews"], ensure_ascii=False, indent=2))
    plan = plans[-1]
    assert len(plan["ingredients"]) == 1
    assert Decimal(plan["ingredients"][0]["amount"]) == 5
    result, brief = live("Actually make it for 40 people, keeping the same recipe and budget.")
    assert brief.portions == 40 and brief.budget_gross == 100
    plan = next(m["meal_plan"] for m in reversed(result["messages"]) if m["meal_plan"])
    assert Decimal(plan["ingredients"][0]["amount"]) == 10


def test_live_direct_product_request_keeps_chat_budget_and_unsupported_requirement(live):
    result, brief = live(
        "Build a product list for 10 litres of milk product 464306. Hard budget 1 euro. "
        "It must be vegan; if that cannot be verified keep the requirement and flag it."
    )
    assert brief.starting_point == "products" and brief.budget_gross == 1
    assert any("vegan" in r.lower() for r in brief.requirements.unsupported)
    assert not any(p["order_id"] for p in result["purchases"])
    assert all(p["policy_outcome"] in ("denied", "needs_resolution") for p in result["purchases"])
