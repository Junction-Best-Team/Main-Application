"""Recipe planning regressions with authored recipes/provider replies; no live calls."""

import json
from copy import deepcopy

import pytest
import test_agent as fixtures
from test_agent import FakeService, call, reply, scripted

from aimo import agent
from aimo.agent_tools import ToolSession
from aimo.db import Problem

config = fixtures.config
identity = fixtures.identity
database = fixtures.database
reset_buyers = fixtures.reset_buyers


def incomplete_carbonara():
    return {
        "recipe": {
            "id": "authored:carbonara", "title": "Carbonara", "summary": "Authored test recipe",
            "base_servings": 4, "category": "main", "instructions": ["Cook the pasta."],
            "ingredients": [
                {"id": "pasta", "name": "Spaghetti", "quantity": "400", "unit": "g",
                 "scaling": "linear", "form": "dry"},
                {"id": "guanciale", "name": "Guanciale", "quantity": "200", "unit": "g",
                 "scaling": "linear", "form": "cured"},
                {"id": "yolks", "name": "Egg yolks", "quantity": "6", "unit": "piece",
                 "scaling": "linear", "form": "raw"},
                {"id": "egg", "name": "Whole egg", "quantity": "2", "unit": "piece",
                 "scaling": "linear", "form": "raw"},
                {"id": "pecorino", "name": "Pecorino romano", "quantity": "120", "unit": "g",
                 "scaling": "linear", "form": "hard cheese"},
                {"id": "pepper", "name": "Black pepper", "quantity": "2.3", "unit": "g",
                 "scaling": "damped", "form": "ground"},
                {"id": "salt", "name": "Salt for the water", "quantity": None, "unit": "toTaste",
                 "scaling": "fixed", "form": "unspecified"},
            ],
        },
        "version": "v1", "source": "authored-fixture", "attribution": "Authored test recipe",
        "license": "test-fixture",
    }


def estimate():
    # Invented test quantities, not reviewed culinary/source facts.
    return {
        "title": "Carbonara estimate", "base_servings": 4, "portions": 200,
        "ingredients": [
            {"name": "Spaghetti", "amount": "400", "unit": "g"},
            {"name": "Guanciale", "amount": "200", "unit": "g"},
            {"name": "Egg yolks", "amount": "6", "unit": "piece"},
            {"name": "Whole egg", "amount": "2", "unit": "piece"},
            {"name": "Pecorino romano", "amount": "120", "unit": "g"},
            {"name": "Black pepper", "amount": "2", "unit": "g"},
            {"name": "Salt for the water", "amount": "40", "unit": "g"},
        ],
        "notes": ["Salt and pepper are assistant estimates for customer review."],
    }


def test_recipe_detail_identifies_pepper_and_salt_gaps_without_selecting_a_plan(identity):
    service = FakeService(identity)
    source = incomplete_carbonara()
    service.get_recipe = lambda *_: deepcopy(source)
    session = ToolSession(identity, service)
    result = session.invoke("get_recipe", json.dumps({"recipe_id": "authored:carbonara", "version": "v1"}))
    assert {i["ingredient"] for i in result["planning_issues"]} == {"Black pepper", "Salt for the water"}
    reasons = " ".join(i["reason"] for i in result["planning_issues"])
    assert "scaling rule" in reasons and "quantity is unspecified" in reasons
    assert result["recipe"]["ingredients"][-2]["scaling"] == "damped"
    assert result["recipe"]["ingredients"][-1]["quantity"] is None
    assert session.plan is None and service.calls == []


def test_incomplete_recipe_cannot_lock_the_turn_and_recovers_to_scaled_estimate(
    monkeypatch, config, identity
):
    service = FakeService(identity)
    reads = []

    def detail(*_):
        reads.append("get_recipe")
        return incomplete_carbonara()

    service.get_recipe = detail
    service.scale_recipe = lambda *_: pytest.fail("An incomplete candidate must not create a saved plan")
    reference = {"recipe_id": "authored:carbonara", "version": "v1"}
    seen = scripted(monkeypatch, [
        # Parallel detail read must reach the parent cache before scaling's barrier.
        reply(call("get_recipe", reference), call("scale_recipe", reference | {"portions": 200})),
        reply(call("draft_recipe", estimate())),
        reply(call("get_product", {"product_id": "pasta"})),
        reply(text="I planned an estimate for 200 portions; salt and pepper are estimated."),
    ])
    result = agent.run_turn(identity, [{"role": "user", "content": "i want to sell 200 carbonara"}], service)
    tools = [json.loads(m["content"]) for m in seen[1]["messages"] if m["role"] == "tool"]
    assert tools[-1]["error"]["code"] == "RECIPE_NOT_SCALABLE"
    assert tools[-1]["purchase_authorized"] is False
    assert reads == ["get_recipe"]
    assert result.meal_plan.recipe_plan_id is None and result.meal_plan.portions == 200
    amounts = {i.name: (i.amount, i.unit) for i in result.meal_plan.ingredients}
    assert amounts == {
        "Spaghetti": ("20", "KG"), "Guanciale": ("10", "KG"), "Egg yolks": ("300", "piece"),
        "Whole egg": ("100", "piece"), "Pecorino romano": ("6", "KG"),
        "Black pepper": ("0.1", "KG"), "Salt for the water": ("2", "KG"),
    }
    assert "Assistant-drafted recipe estimate" in result.meal_plan.notes[0]
    assert "More product searches" not in result.text
    assert result.proposal_id is None and [c[0] for c in service.calls] == ["product"]


@pytest.mark.parametrize("change", ["complete", "unsupported_unit", "unspecified_form"])
def test_candidate_preflight_preserves_supported_saved_recipe_flow(identity, change):
    detail = incomplete_carbonara()
    detail["recipe"]["ingredients"] = detail["recipe"]["ingredients"][:1]
    if change == "unsupported_unit":
        detail["recipe"]["ingredients"][0]["unit"] = "bunch"
    elif change == "unspecified_form":
        detail["recipe"]["ingredients"][0]["form"] = "unspecified"
    service = FakeService(identity)
    service.get_recipe = lambda *_: deepcopy(detail)
    service.scale_recipe = lambda *_: fixtures.meal(False) | {
        "recipe_plan_id": "saved", "recipe_plan_revision": 1
    }
    session = ToolSession(identity, service)
    request = json.dumps({"recipe_id": "authored:carbonara", "version": "v1", "portions": 200})
    if change == "complete":
        assert session.invoke("scale_recipe", request)["meal_plan"]["recipe_plan_id"] == "saved"
    else:
        with pytest.raises(Problem) as error:
            session.invoke("scale_recipe", request)
        assert error.value.code == "RECIPE_NOT_SCALABLE" and session.plan is None
