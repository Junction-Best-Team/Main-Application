# ruff: noqa: F811
"""Pure request merging and source-preserving calculation regressions."""

from types import SimpleNamespace

import pytest
from test_agent import FakeService, identity, invoke, matched_session, meal, purchase  # noqa: F401

from aimo.agent_tools import ToolSession
from aimo.db import Problem
from aimo.guardrails import Guardrails, GuardResult, Verdict
from aimo.request_brief import RequestBrief


@pytest.fixture(scope="session", autouse=True)
def database():
    yield


@pytest.fixture(autouse=True)
def reset_buyers():
    yield


def brief(**changes):
    return {
        "intent": "build_list",
        "goal": "Carbonara",
        "starting_point": "dish",
        "portions": 200,
        **changes,
    }


def test_limits_are_applied_to_the_agent_prepare_path_too(identity):
    service = FakeService(identity)
    session = matched_session(identity, service)
    invoke(
        session, "record_request", brief(budget_gross="80", requirements={"unsupported": ["vegan"]})
    )
    invoke(session, "prepare_order", purchase())
    prepared = next(c[2] for c in service.calls if c[0] == "prepare")
    assert prepared.budget_gross == 80
    assert prepared.requirements.unsupported == ["vegan"]


def test_own_recipe_preserves_quantities_and_separates_estimated_additions(identity):
    session = ToolSession(identity, FakeService(identity))
    invoke(
        session,
        "record_request",
        brief(
            starting_point="customer_recipe",
            recipe_reference="Customer's warm milk recipe: 0.5 L for 2 people",
            portions=20,
        ),
    )
    result = invoke(
        session,
        "draft_recipe",
        {
            "title": "Warm milk",
            "source": "customer_recipe",
            "base_servings": 2,
            "portions": 20,
            "ingredients": [{"name": "Milk", "amount": "0.5", "unit": "l"}],
        },
    )
    assert result["meal_plan"]["ingredients"][0]["amount"] == "5"
    assert "Customer-supplied recipe" in result["meal_plan"]["notes"][0]
    assert not any("Assistant-drafted" in n for n in result["meal_plan"]["notes"])


@pytest.mark.parametrize("change", [{"intent": "explore"}, {"missing_facts": ["How many people?"]}])
def test_exploration_or_missing_material_facts_cannot_become_a_cart(identity, change):
    session = matched_session(identity, FakeService(identity))
    invoke(session, "record_request", brief(**change))
    with pytest.raises(Problem, match="first"):
        invoke(session, "prepare_order", purchase())
    with pytest.raises(Problem) as error:
        invoke(session, "publish_meal_plan", meal())
    assert error.value.code == "REQUEST_NOT_READY"


@pytest.mark.parametrize("verdict", [Verdict.BLOCKED, Verdict.UNCERTAIN, Verdict.UNAVAILABLE])
def test_unverified_request_changes_cannot_overwrite_the_saved_understanding(identity, verdict):
    session = ToolSession(identity, FakeService(identity))
    invoke(session, "record_request", brief(budget_gross="100"))
    guard = object.__new__(Guardrails)
    guard.messages = [{"role": "user", "content": "Keep the same budget."}]
    guard.evaluate = lambda *a: GuardResult("request_brief", "enforce", verdict)
    session.guard = guard
    with pytest.raises(Problem) as error:
        invoke(session, "record_request", brief(budget_gross="1000"))
    assert error.value.code == "REQUEST_BRIEF_UNVERIFIED"
    assert session.brief.budget_gross == 100


def test_enforcement_requires_current_understanding_before_preparation(identity):
    session = matched_session(identity | {"_conversation_id": "test"}, FakeService(identity))
    session.guard = SimpleNamespace(enforcing=True)
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", purchase())
    assert error.value.code == "REQUEST_BRIEF_REQUIRED"


def test_portion_change_requires_recalculation_before_preparation(identity):
    session = matched_session(identity, FakeService(identity))
    invoke(session, "record_request", brief(portions=150))
    with pytest.raises(Problem) as error:
        invoke(session, "prepare_order", purchase())
    assert error.value.code == "REQUEST_QUANTITY_CHANGED"
    invoke(session, "resize_plan", {"portions": 150})
    assert session.plan.portions == 150 and session.plan.ingredients[0].amount == "15"


def test_brief_has_no_authority_or_confirmation_fields():
    with pytest.raises(ValueError):
        RequestBrief.model_validate(brief(approved=True))
