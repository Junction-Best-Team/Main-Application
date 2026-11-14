"""Q-44 / BAS-009: a basket mismatch tells the agent EXACTLY what to send, as structured details.

Pure tests, authored fixtures only (`aimo.fixtures`), no database, no supplier. The owner's decision:
"Yes, have the agent always need to request with the units attached. And we provide with what the
agent needs." The basket stays refused when its units differ from the plan; the error carries the
required amount and unit per product.
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from aimo.basket_errors import (
    BasketProblem,
    mismatch_details,
    mismatch_problem,
    required_basket,
    unit_conversion_problem,
)
from aimo.db import Problem
from aimo.fixtures import fixture_facts

MILK = "464306"  # fixture: sales ST, KI = 20 ST, one litre per ST (known)


def milk():
    return {MILK: fixture_facts()[0]}


def row(product_id, amount, unit, name=None):
    r = {"product_id": product_id, "amount": amount, "unit": unit}
    if name:
        r["name"] = name
    return r


def sent(product_id, amount, unit):
    return {"product_id": product_id, "amount": amount, "unit": unit}


PLAN = [
    row("pasta", "20", "KG", "pasta"),
    row("eggs", "100", "piece", "eggs"),
    row("pork", "6", "KG", "guanciale"),
]


# --- required_basket ------------------------------------------------------------------------


def test_same_unit_contributions_are_summed_in_the_plan_unit():
    required = required_basket(
        [row("pasta", "20", "KG", "pasta"), row("pasta", "0.5", "KG", "extra")]
    )
    assert required == [
        {"product_id": "pasta", "amount": "20.5", "unit": "KG", "ingredients": ["extra", "pasta"]}
    ]


def test_sorted_by_product_id_whatever_the_input_order():
    forward = required_basket(PLAN)
    assert [r["product_id"] for r in forward] == ["eggs", "pasta", "pork"]
    assert required_basket(list(reversed(PLAN))) == forward


def test_units_that_combine_through_catalog_evidence_use_the_priority_unit():
    # 5 L + 1 KI (= 20 ST = 20 L) -> 25 L: the unit of the priority order
    required = required_basket([row(MILK, "5", "L", "cream"), row(MILK, "1", "KI", "soup")], milk())
    assert required == [
        {"product_id": MILK, "amount": "25", "unit": "L", "ingredients": ["cream", "soup"]}
    ]


def test_unknown_conversion_gives_no_amount_and_a_reason():
    required = required_basket([row(MILK, "2", "KG", "a"), row(MILK, "3", "L", "b")], milk())
    assert len(required) == 1
    entry = required[0]
    assert entry["product_id"] == MILK
    assert entry["amount"] is None and entry["unit"] is None
    assert entry["reason"]


def test_different_units_without_product_facts_are_unknown():
    entry = required_basket([row("x", "1", "KG"), row("x", "2", "L")])[0]
    assert entry["amount"] is None and "not loaded" in entry["reason"]


def test_amounts_are_exact_decimal_strings_never_floats():
    required = required_basket(
        [row("p", Decimal("0.1"), "KG"), row("p", "0.2", "KG"), row("p", 1, "KG")]
    )
    assert required[0]["amount"] == "1.3"
    assert isinstance(required[0]["amount"], str)
    with pytest.raises(TypeError):
        required_basket([row("p", 0.1, "KG")])


# --- mismatch_details -----------------------------------------------------------------------


def exact_lines():
    return [sent("pasta", "20", "KG"), sent("eggs", "100", "piece"), sent("pork", "6", "KG")]


def test_matching_lines_report_no_problem():
    d = mismatch_details(required_basket(PLAN), exact_lines())
    assert d["missing"] == [] and d["unexpected"] == [] and d["wrong_amount_or_unit"] == []
    assert d["required"] == required_basket(PLAN)


def test_missing_line():
    d = mismatch_details(required_basket(PLAN), exact_lines()[:2])
    assert d["missing"] == ["pork"]
    assert d["unexpected"] == [] and d["wrong_amount_or_unit"] == []
    assert [s["product_id"] for s in d["sent"]] == ["eggs", "pasta"]


def test_extra_line():
    d = mismatch_details(required_basket(PLAN), [*exact_lines(), sent("salt", "1", "KG")])
    assert d["unexpected"] == ["salt"]
    assert d["missing"] == [] and d["wrong_amount_or_unit"] == []


def test_wrong_unit():
    lines = [sent("pasta", "20000", "G"), *exact_lines()[1:]]
    d = mismatch_details(required_basket(PLAN), lines)
    assert d["wrong_amount_or_unit"] == [
        {
            "product_id": "pasta",
            "required": {"amount": "20", "unit": "KG"},
            "sent": {"amount": "20000", "unit": "G"},
        }
    ]
    assert d["missing"] == [] and d["unexpected"] == []


def test_wrong_amount():
    lines = [
        sent("pasta", Decimal("20"), "KG"),
        sent("eggs", "99", "piece"),
        sent("pork", "6", "KG"),
    ]
    d = mismatch_details(required_basket(PLAN), lines)
    assert d["wrong_amount_or_unit"] == [
        {
            "product_id": "eggs",
            "required": {"amount": "100", "unit": "piece"},
            "sent": {"amount": "99", "unit": "piece"},
        }
    ]


def test_equal_values_with_different_spelling_match():
    lines = [sent("pasta", "20.000", "KG"), sent("eggs", 100, "piece"), sent("pork", "6.0", "KG")]
    d = mismatch_details(required_basket(PLAN), lines)
    assert d["wrong_amount_or_unit"] == []


def test_several_products_wrong_in_different_ways():
    lines = [sent("pasta", "19", "KG"), sent("salt", "1", "KG"), sent("pork", "6", "KG")]
    d = mismatch_details(required_basket(PLAN), lines)
    assert d["missing"] == ["eggs"]
    assert d["unexpected"] == ["salt"]
    assert [w["product_id"] for w in d["wrong_amount_or_unit"]] == ["pasta"]


def test_sent_lines_accept_objects_and_are_sorted():
    lines = [
        SimpleNamespace(product_id=p, amount=Decimal(a), unit=u)
        for p, a, u in [("pork", "6", "KG"), ("eggs", "100", "piece"), ("pasta", "20", "KG")]
    ]
    d = mismatch_details(required_basket(PLAN), lines)
    assert d["sent"] == [
        {"product_id": "eggs", "amount": "100", "unit": "piece"},
        {"product_id": "pasta", "amount": "20", "unit": "KG"},
        {"product_id": "pork", "amount": "6", "unit": "KG"},
    ]


def test_details_are_independent_of_input_order():
    required = required_basket(PLAN)
    lines = [sent("pasta", "19", "KG"), sent("salt", "1", "KG"), sent("pork", "6", "KG")]
    assert mismatch_details(required, lines) == mismatch_details(
        list(reversed(required)), list(reversed(lines))
    )


def test_one_product_in_two_units_is_combined_before_comparing():
    required = required_basket([row(MILK, "25", "L", "milk")], milk())
    # 5 L + 1 KI = 25 L: matches in the priority unit
    ok = mismatch_details(required, [sent(MILK, "5", "L"), sent(MILK, "1", "KI")], milk())
    assert ok["wrong_amount_or_unit"] == []
    bad = mismatch_details(required, [sent(MILK, "5", "L"), sent(MILK, "2", "KI")], milk())
    assert bad["wrong_amount_or_unit"][0]["sent"]["amount"] == "45"
    assert bad["wrong_amount_or_unit"][0]["required"] == {"amount": "25", "unit": "L"}


def test_a_required_product_with_unknown_conversion_is_not_compared():
    required = required_basket([row(MILK, "2", "KG"), row(MILK, "3", "L")], milk())
    d = mismatch_details(required, [sent(MILK, "5", "L")], milk())
    assert d["missing"] == [] and d["wrong_amount_or_unit"] == []
    assert mismatch_details(required, [], milk())["missing"] == [MILK]


# --- the problem objects --------------------------------------------------------------------


def problem(lines=None):
    return mismatch_problem(
        required_basket(PLAN), lines if lines is not None else exact_lines()[:2]
    )


def test_mismatch_problem_is_a_problem_with_status_422_and_details():
    error = problem()
    assert isinstance(error, BasketProblem) and isinstance(error, Problem)
    assert error.code == "MEAL_BASKET_MISMATCH" and error.status == 422
    assert error.details["missing"] == ["pork"]
    assert error.retry_after is None and str(error) == error.message
    with pytest.raises(Problem) as caught:  # existing `except Problem` code keeps working
        raise problem()
    assert caught.value.code == "MEAL_BASKET_MISMATCH"


def test_message_contains_each_exact_required_line():
    message = problem().message
    for line in ("eggs 100 piece", "pasta 20 KG", "pork 6 KG"):
        assert line in message
    assert "Send exactly: eggs 100 piece; pasta 20 KG; pork 6 KG" in message


def test_message_names_what_is_wrong():
    message = problem([sent("pasta", "19", "KG"), sent("salt", "1", "KG")]).message
    assert "Missing: eggs, pork" in message
    assert "salt" in message and "pasta" in message and "19 KG" in message


def test_combined_unit_line_is_in_the_message():
    error = mismatch_problem(
        required_basket([row(MILK, "5", "L"), row(MILK, "1", "KI")], milk()),
        [sent(MILK, "6", "L")],
        milk(),
    )
    assert f"Send exactly: {MILK} 25 L" in error.message


def test_details_are_json_serialisable_without_floats():
    def walk(value):
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    details = problem().details
    walk(details)
    assert json.loads(json.dumps(details)) == details


def test_unit_conversion_problem():
    required = required_basket([row(MILK, "2", "KG", "a"), row(MILK, "3", "L", "b")], milk())
    error = unit_conversion_problem(MILK, required)
    assert isinstance(error, BasketProblem) and isinstance(error, Problem)
    assert error.code == "UNIT_CONVERSION_UNKNOWN" and error.status == 422
    assert error.details["product_id"] == MILK
    assert error.details["reason"] == required[0]["reason"]
    assert error.details["required"] == required
    assert MILK in error.message and required[0]["reason"] in error.message
    # a single entry works as well as the whole list
    assert unit_conversion_problem(MILK, required[0]).details["reason"] == required[0]["reason"]
