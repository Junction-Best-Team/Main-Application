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
