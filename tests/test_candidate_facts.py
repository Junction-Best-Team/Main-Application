"""The candidate and availability data the model sees say what a good choice needs (owner Q-134 a).

Search results carry, for the inspected candidates, `pack_size_units` (which of L and KG the product's
data converts to packs) and `in_scope` (inside the buyer's approved product scope); availability
results carry `stock_verified` (a Stock line with a real amount). The model may prefer such
products; nothing here relaxes a purchasing check or selects a product for the customer.
"""

from datetime import date, timedelta

import pytest

from aimo import auth
from aimo.agent_tools import ToolSession


@pytest.fixture
def session(service, buyer):
    from uuid import uuid4

    return ToolSession(auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}, service)


def candidates(session, query="milk"):
    result = session.invoke("search_products", f'{{"query":"{query}"}}')
    return {p["id"]: p for p in result["products"] if "pack_size_units" in p}


def test_inspected_candidates_say_which_units_convert_and_whether_they_are_in_scope(session):
    found = candidates(session)
    assert found, "the first three candidates are inspected"
    milk = found.get("464306")
    assert milk is not None
    assert milk["pack_size_units"] == ["L"]  # a structured 1 L volume, no net weight
    assert milk["in_scope"] is True  # the seeded policy lists 464306
    for product in found.values():
        assert set(product["pack_size_units"]) <= {"L", "KG"}
        assert isinstance(product["in_scope"], bool)


def test_a_product_with_a_name_only_size_is_not_marked_convertible(session):
    found = candidates(session, "demo milk 5-pack volume unverified")
    unverified = found.get("465039")
    if unverified is None:
        pytest.skip("the fixture search did not inspect 465039 for this query")
    assert unverified["pack_size_units"] == []
    assert unverified["in_scope"] is False


def lookup(session, *ids):
    day = date.today() + timedelta(days=2)
    return session.invoke(
        "check_price_and_availability",
        '{"product_ids": %s, "delivery_date": "%s"}' % (str(list(ids)).replace("'", '"'), day),
    )["products"]


def test_a_stock_line_with_a_real_amount_is_stock_verified(session):
    assert lookup(session, "464306")["464306"]["stock_verified"] is True


def test_a_placeholder_amount_is_not_stock_verified(session, connector):
    connector.stock["464398"] = "999999"  # the supplier's "unknown quantity"
    products = lookup(session, "464306", "464398")
    assert products["464306"]["stock_verified"] is True
    assert products["464398"]["stock_verified"] is False
    assert any(r["code"] == "UNVERIFIED_STOCK" for r in products["464398"]["reasons"])
