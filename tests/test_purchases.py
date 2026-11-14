"""Authority context and snapshot construction: the failure branches behind a proposal.

Unknown is never zero: whatever cannot be established leaves the total unresolved. These tests
break one fact at a time and check the resulting reason code and that no total is invented.
"""

from copy import deepcopy
from datetime import date, timedelta

import pytest

from aimo import purchases
from aimo.db import Problem, connection, js
from aimo.purchases import build_snapshot, context, material_fingerprint
from aimo.schemas import PrepareRequest
from aimo.upstream import FixtureClient


def req(request_data, lines, **patch):
    return PrepareRequest.model_validate({**request_data, "lines": lines, **patch})


def codes(snapshot):
    return {r["code"] for r in snapshot["reasons"]}


def patch_products(monkeypatch, mutate):
    original = purchases.load_products

    def wrapped(c, ids):
        products = deepcopy(original(c, ids))
        for pid, change in mutate.items():  # only products this call actually loaded
            if pid in products:
                change(products[pid])
        return products

    monkeypatch.setattr(purchases, "load_products", wrapped)


class Connector(FixtureClient):
    """Fixture upstream whose raw response a test may edit."""

    def __init__(self, edit=lambda raw: None):
        super().__init__()
        self.edit = edit

    def lookup(self, customer, ids, delivery_date):
        raw = super().lookup(customer, ids, delivery_date)
        self.edit(raw)
        return raw


# --- context -------------------------------------------------------------------------------------


def test_context_refuses_an_inactive_identity(agent):
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='demo-agent'")
        with pytest.raises(Problem) as error:
            context(c, agent)
    assert (error.value.code, error.value.status) == ("AUTHORITY_REVOKED", 403)


def test_context_refuses_a_buyer_without_a_current_policy(agent):
    with connection() as c:
        c.execute("UPDATE buyers SET current_policy=99 WHERE id='demo-hotel'")
        with pytest.raises(Problem) as error:
            context(c, agent)
    assert (error.value.code, error.value.status) == ("MISSING_POLICY", 409)


def test_context_never_defaults_an_invalid_policy_to_permission(agent):
    with connection() as c:
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)",
            (js({"currency": "EUR"}),),
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
        with pytest.raises(Problem) as error:
            context(c, agent)
    assert error.value.code == "INVALID_POLICY_CONFIGURATION"


@pytest.mark.parametrize(
    "authority",
    [{}, {"currency": "EUR", "autonomous_limit": "1500"}, {"autonomous_limit": "999999"}],
)
def test_context_ignores_the_content_of_an_agent_authority(agent, authority):
    # Q-35 replacement: an agent holds no authority, so no stored shape can invalidate it.
    with connection() as c:
        c.execute("UPDATE identities SET authority=%s WHERE id='demo-agent'", (js(authority),))
        _, _, actor, _ = context(c, agent)
    assert actor["id"] == "demo-agent"


def test_context_still_rejects_an_invalid_approver_authority(buyer):
    with connection() as c:
        c.execute("UPDATE identities SET authority=%s WHERE id='buyer'", (js({}),))
        with pytest.raises(Problem) as error:
            context(c, buyer)
    assert error.value.code == "INVALID_POLICY_CONFIGURATION"


def test_context_lists_only_valid_active_approvers(agent):
    with connection() as c:
        _, _, _, approvers = context(c, agent)
        assert [a["id"] for a in approvers] == ["buyer"]
        c.execute("UPDATE identities SET authority=%s WHERE id='buyer'", (js({"max_gross": "x"}),))
        _, _, actor, approvers = context(c, agent)
    assert actor["id"] == "demo-agent"
    assert approvers == []  # a broken approver configuration grants no exception authority


# --- build_snapshot: request-level checks --------------------------------------------------------


def test_delivery_in_the_past_is_denied(agent, request_data):
    request = req(
        request_data, request_data["lines"], delivery_date=str(date.today() - timedelta(days=3))
    )
    snapshot, _, _ = build_snapshot(agent, request, FixtureClient())
    past = [r for r in snapshot["reasons"] if r["code"] == "DELIVERY_IN_PAST"]
    assert past and past[0]["severity"] == "denied"


def test_unknown_product_makes_the_total_unresolved(agent, request_data):
    request = req(request_data, [{"product_id": "no-such-product", "amount": "1", "unit": "L"}])
    snapshot, _, _ = build_snapshot(agent, request, FixtureClient())
    assert {"PRODUCT_UNKNOWN", "TOTAL_UNRESOLVED"} <= codes(snapshot)
    assert snapshot["gross_total"] is None and snapshot["lines"] == []


def test_withdrawn_product_is_denied(agent, request_data, monkeypatch):
    patch_products(monkeypatch, {"464306": lambda p: p.update(deleted=True)})
    snapshot, _, _ = build_snapshot(
        agent, req(request_data, request_data["lines"]), FixtureClient()
    )
    deleted = [r for r in snapshot["reasons"] if r["code"] == "PRODUCT_DELETED"]
    assert deleted and deleted[0]["severity"] == "denied"


def test_too_many_materials_are_refused_before_calling_upstream(agent, request_data, monkeypatch):
    def many(p):
        p["deposits"] = [
            {"material": f"dep-{i}", "quantity": "1", "unit": "ST"} for i in range(101)
        ]

    patch_products(monkeypatch, {"464306": many})

    class NoCalls:
        def lookup(self, *args):
            raise AssertionError("upstream must not be queried")

    with pytest.raises(Problem) as error:
        build_snapshot(agent, req(request_data, request_data["lines"]), NoCalls())
    assert (error.value.code, error.value.status) == ("TOO_MANY_MATERIALS", 422)


def test_variable_weight_product_is_unresolved(agent, request_data):
    request = req(request_data, [{"product_id": "460675", "amount": "20", "unit": "KG"}])
    snapshot, _, _ = build_snapshot(agent, request, FixtureClient())
    assert "VARIABLE_WEIGHT_UNRESOLVED" in codes(snapshot)


def test_unconvertible_quantity_is_unresolved_not_guessed(agent, request_data):
    request = req(request_data, [{"product_id": "465039", "amount": "10", "unit": "L"}])
    snapshot, _, _ = build_snapshot(agent, request, FixtureClient())
    assert {"QUANTITY_UNRESOLVED", "TOTAL_UNRESOLVED"} <= codes(snapshot)
    assert snapshot["lines"][0]["quantity"]["sales_quantity"] is None
    assert snapshot["gross_total"] is None


def test_missing_price_leaves_the_line_and_total_unpriced(agent, request_data):
    connector = Connector(lambda raw: raw["price"]["products"][0].update(catalogPrice=None))
    snapshot, _, _ = build_snapshot(agent, req(request_data, request_data["lines"]), connector)
    assert {"MISSING_PRICE", "TOTAL_UNRESOLVED"} <= codes(snapshot)
    assert snapshot["lines"][0]["gross"] is None and snapshot["gross_total"] is None


def test_insufficient_stock_is_reported_with_the_available_quantity(agent, request_data):
    request = req(request_data, [{"product_id": "463380", "amount": "800", "unit": "L"}])
    snapshot, _, _ = build_snapshot(agent, request, FixtureClient())
    shortage = [r for r in snapshot["reasons"] if r["code"] == "INSUFFICIENT_STOCK"]
    assert shortage and "Only 698" in shortage[0]["message"]
    assert snapshot["gross_total"] is not None  # priced, just not fulfillable


def test_proposal_expiry_is_the_earliest_supplier_limit(agent, request_data):
    snapshot, expires, version = build_snapshot(
        agent, req(request_data, request_data["lines"]), FixtureClient()
    )
    from aimo.config import settings
    from aimo.db import now

    ttl = timedelta(seconds=settings().proposal_ttl_seconds)
    assert now() < expires <= now() + ttl
    assert version == 1


# --- deposits ------------------------------------------------------------------------------------

DEPOSIT_LINE = [{"product_id": "460123", "amount": "12", "unit": "BOT"}]


def break_deposit(**changes):
    return {"460123": lambda p: p.update(deposits=[{**p["deposits"][0], **changes}])}


def test_deposit_is_priced_into_the_line(agent, request_data):
    snapshot, _, _ = build_snapshot(agent, req(request_data, DEPOSIT_LINE), FixtureClient())
    line = snapshot["lines"][0]
    assert line["deposit_lines"][0]["material"] == "demo-deposit"
    assert line["deposit_lines"][0]["quantity"] == "12"
    assert snapshot["deposits_gross"] == line["deposits_gross"] == "1.56"
    assert "DEPOSIT_UNRESOLVED" not in codes(snapshot)


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "NOPE"},  # no conversion factor for the deposit unit
        {"material": "ghost-material"},  # deposit product absent from the catalog
        {"quantity": "0"},  # nothing to price
        {"quantity": "not-a-number"},
    ],
)
def test_unresolvable_deposit_never_counts_as_zero(agent, request_data, monkeypatch, changes):
    patch_products(monkeypatch, break_deposit(**changes))
    snapshot, _, _ = build_snapshot(agent, req(request_data, DEPOSIT_LINE), FixtureClient())
    assert {"DEPOSIT_UNRESOLVED", "TOTAL_UNRESOLVED"} <= codes(snapshot)
    assert snapshot["gross_total"] is None and snapshot["deposits_gross"] is None
    assert snapshot["lines"][0]["deposit_lines"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(deleted=True),
        lambda p: p.update(conflicts=["UNIT_FACTOR_CONFLICT"]),
        lambda p: p.update(units={"ST": "0"}),
    ],
    ids=["withdrawn", "conflicting-units", "zero-factor"],
)
def test_unusable_deposit_product_leaves_the_total_unresolved(
    agent, request_data, monkeypatch, mutate
):
    patch_products(monkeypatch, {"demo-deposit": mutate})
    snapshot, _, _ = build_snapshot(agent, req(request_data, DEPOSIT_LINE), FixtureClient())
    assert "DEPOSIT_UNRESOLVED" in codes(snapshot)
    assert snapshot["gross_total"] is None


def test_deposit_without_a_current_price_is_unresolved(agent, request_data):
    def drop_deposit_price(raw):
        for row in raw["price"]["products"]:
            if row["productId"] == "demo-deposit":
                row["catalogPrice"] = None

    snapshot, _, _ = build_snapshot(
        agent, req(request_data, DEPOSIT_LINE), Connector(drop_deposit_price)
    )
    assert {"DEPOSIT_UNRESOLVED", "TOTAL_UNRESOLVED"} <= codes(snapshot)
    assert snapshot["gross_total"] is None


# --- fingerprint ---------------------------------------------------------------------------------


def test_material_fingerprint_ignores_lookup_time_but_not_price(agent, request_data):
    request = req(request_data, request_data["lines"])
    first, _, version = build_snapshot(agent, request, FixtureClient())
    again, _, _ = build_snapshot(agent, request, FixtureClient())
    base = material_fingerprint({"r": 1}, first, version)
    assert base == material_fingerprint({"r": 1}, again, version)
    assert base != material_fingerprint({"r": 2}, first, version)
    assert base != material_fingerprint({"r": 1}, first, version + 1)
    dearer = FixtureClient()
    dearer.price_multiplier = 2
    pricier, _, _ = build_snapshot(agent, request, dearer)
    assert base != material_fingerprint({"r": 1}, pricier, version)
