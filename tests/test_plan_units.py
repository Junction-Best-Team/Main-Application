# ruff: noqa: F811
"""Live round 1 (SB-28): a Finnish plan in ml, l and dl made every basket line (in L) a MEAL_BASKET_MISMATCH.

A free-form plan is stored in canonical units (L, KG) when the conversion is exact, so the basket the model
prepares in L or KG matches. Saved-recipe and server-scaled draft plans are never touched. The draft
mismatch error now lists the exact lines to keep (SB-05).
"""

import json
from copy import deepcopy

import pytest
from test_agent import (  # noqa: F401
    FakeService,
    call,
    database,
    identity,
    invoke,
    meal,
    purchase,
    reset_buyers,
)

from aimo.agent_tools import ToolSession
from aimo.db import Problem

NAMES = ["pasta", "eggs", "pork", "cheese", "pepper"]


def session_with(identity, units):
    session = ToolSession(identity, FakeService(identity))
    for name in NAMES:
        invoke(session, "get_product", {"product_id": name})
    plan = meal()
    for item, (amount, unit) in zip(plan["ingredients"], units):
        item["amount"], item["unit"] = amount, unit
    return session, plan


def test_millilitres_decilitres_and_grams_become_litres_and_kilograms(identity):
    units = [("750", "ml"), ("4", "l"), ("3", "dl"), ("20000", "g"), ("0.5", "kg")]
    session, plan = session_with(identity, units)
    invoke(session, "publish_meal_plan", plan)
    stored = [(i.amount, i.unit) for i in session.plan.ingredients]
    assert stored == [("0.75", "L"), ("4", "L"), ("0.3", "L"), ("20", "KG"), ("0.5", "KG")]


def test_the_basket_in_canonical_units_now_matches_the_plan(identity):
    units = [("750", "ml"), ("4", "l"), ("3", "dl"), ("20000", "g"), ("500", "g")]
    session, plan = session_with(identity, units)
    invoke(session, "publish_meal_plan", plan)
    order = purchase()
    for line, (amount, unit) in zip(
        order["lines"], [("0.75", "L"), ("4", "L"), ("0.3", "L"), ("20", "KG"), ("0.5", "KG")]
    ):
        line["amount"], line["unit"] = amount, unit
    try:
        invoke(session, "prepare_order", order)
    except Problem as exc:  # other checks may refuse the fixture products; not the quantities
        assert exc.code != "MEAL_BASKET_MISMATCH", exc.message


@pytest.mark.parametrize("amount,unit", [("0.00025", "g"), ("5", "tl"), ("2", "pcs"), ("3", "KG")])
def test_inexact_or_unknown_units_are_left_as_they_are(identity, amount, unit):
    session, plan = session_with(identity, [(amount, unit)] + [("1", "KG")] * 4)
    if unit == "g":  # 0.00025 kg has 5 decimals: not storable, so no silent rounding
        with pytest.raises(Problem):
            invoke(session, "publish_meal_plan", plan)
        return
    invoke(session, "publish_meal_plan", plan)
    assert (session.plan.ingredients[0].amount, session.plan.ingredients[0].unit) == (amount, unit)


def test_normalise_units_is_exact_and_leaves_the_rest_alone():
    from aimo.agent_tools import normalise_units
    from aimo.chat_schemas import MealPlan

    plan = deepcopy(meal())
    plan["ingredients"][0].update(amount="750", unit="ml")
    plan["ingredients"][1].update(amount="2", unit="piece")
    out = normalise_units(MealPlan.model_validate(plan)).ingredients
    assert (out[0].amount, out[0].unit) == ("0.75", "L") and (out[1].amount, out[1].unit) == (
        "2",
        "piece",
    )


def test_the_draft_mismatch_lists_the_exact_lines_to_keep(identity):
    from test_agent import draft_basis

    session = ToolSession(identity, FakeService(identity))
    session.invoke("draft_recipe", json.dumps(draft_basis()))
    plan = session.plan.model_dump(mode="json")
    plan["ingredients"][0]["amount"] = "999"
    with pytest.raises(Problem) as error:
        session.invoke("publish_meal_plan", json.dumps(plan))
    assert error.value.code == "DRAFT_QUANTITY_MISMATCH"
    expected = error.value.details["expected"]
    assert expected and {"name", "amount", "unit"} <= set(expected[0])
    assert "Keep exactly" in error.value.message
