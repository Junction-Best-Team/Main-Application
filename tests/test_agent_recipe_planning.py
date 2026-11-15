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


def recipe_summary(detail):
    recipe = detail["recipe"]
    return {
        "recipe_id": recipe["id"], "version": detail["version"], "title": recipe["title"],
        "summary": recipe["summary"], "base_servings": recipe["base_servings"],
    }


@pytest.mark.parametrize("recipe_id,title", [
    ("authored:carbonara", "Carbonara"),
    ("authored:lasagne", "Lasagne"),
    ("authored:stew", "Vegetable stew"),
])
def test_recipe_search_returns_full_best_match_for_any_recipe(identity, recipe_id, title):
    detail = incomplete_carbonara()
    detail["recipe"].update(id=recipe_id, title=title)
    alternative = deepcopy(detail)
    alternative["recipe"].update(id="authored:alternative", title="Alternative")
    service = FakeService(identity)
    reads = []
    service.search_recipes = lambda *_: {
        "recipes": [recipe_summary(detail), recipe_summary(alternative)],
        "rerank_status": "disabled", "note": "Authored discovery results.",
    }

    def read(_, request):
        reads.append(request.recipe_id)
        return deepcopy(detail if request.recipe_id == recipe_id else alternative)

    service.get_recipe = read
    session = ToolSession(identity, service)
    result = session.invoke("search_recipes", json.dumps({"query": title}))
    best = result["best_match"]
    assert best["recipe"]["id"] == recipe_id and best["recipe"]["title"] == title
    assert len(best["recipe"]["ingredients"]) == len(detail["recipe"]["ingredients"]) == 7
    assert best["recipe"]["instructions"] == detail["recipe"]["instructions"]
    assert best["attribution"] == detail["attribution"] and best["license"] == detail["license"]
    assert {i["ingredient"] for i in best["planning_issues"]} == {"Black pepper", "Salt for the water"}
    assert "ingredients" not in result["recipes"][1]  # Alternatives remain bounded summaries.
    assert reads == [recipe_id] and session.plan is None and service.calls == []
    # A specific-ID read reuses the best match; an alternative remains available on demand.
    assert session.invoke("get_recipe", json.dumps({"recipe_id": recipe_id, "version": "v1"})) == best
    loaded = session.invoke("get_recipe", json.dumps({"recipe_id": "authored:alternative", "version": "v1"}))
    assert loaded["recipe"]["id"] == "authored:alternative"
    assert reads == [recipe_id, "authored:alternative"]


def test_empty_recipe_search_does_not_read_a_recipe(identity):
    service = FakeService(identity)
    service.search_recipes = lambda *_: {"recipes": [], "rerank_status": "disabled", "note": "No matches."}
    service.get_recipe = lambda *_: pytest.fail("Empty searches have no detail to read")
    result = ToolSession(identity, service).invoke("search_recipes", '{"query":"missing recipe"}')
    assert result["recipes"] == [] and result["best_match"] is None


def test_search_best_match_scales_without_another_detail_tool_or_policy_lookup(
    monkeypatch, config, identity
):
    from aimo.recipe_schemas import Recipe
    from aimo.recipes import scaled_plan

    detail = incomplete_carbonara()
    for item in detail["recipe"]["ingredients"]:
        item["scaling"] = "linear"
        if item["quantity"] is None:
            item.update(quantity="40", unit="g", form="granular")
    service = FakeService(identity)
    calls = []

    def search(*_):
        calls.append("search")
        return {"recipes": [recipe_summary(detail)], "rerank_status": "disabled", "note": "Fixture."}

    def read(*_):
        calls.append("detail")
        return deepcopy(detail)

    def scale(_, request):
        calls.append("scale")
        plan = scaled_plan(Recipe.model_validate(detail["recipe"]), request.portions)
        plan.recipe_plan_id, plan.recipe_plan_revision = "saved", 1
        return plan.model_dump(mode="json")

    service.search_recipes, service.get_recipe, service.scale_recipe = search, read, scale
    seen = scripted(monkeypatch, [
        reply(call("search_recipes", {"query": "carbonara"})),
        reply(call("scale_recipe", {"recipe_id": "authored:carbonara", "version": "v1", "portions": 200})),
        reply(text="I planned carbonara for 200 portions."),
    ])
    result = agent.run_turn(identity, fixtures.HISTORY, service)
    returned = json.loads(next(m["content"] for m in seen[1]["messages"] if m["role"] == "tool"))["result"]
    assert len(returned["best_match"]["recipe"]["ingredients"]) == 7
    assert returned["best_match"]["planning_issues"] == []
    assert calls == ["search", "detail", "scale"]  # Parallel cache merge avoids a second detail read.
    assert result.meal_plan.recipe_plan_id == "saved" and result.meal_plan.portions == 200
    assert len(result.meal_plan.ingredients) == 7 and result.proposal_id is None
    assert service.calls == []
