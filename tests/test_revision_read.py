"""PER-003: read a proposal and a recipe plan by ID AND REVISION, buyer-scoped.

Found by the WS-D end-to-end check: after a repricing the earlier revision of a ready_to_commit
proposal (no approval row) was unreadable through any route, and a recipe plan could only be read
at its current revision. `GET /api/purchases/{id}?revision=N` and
`Service.get_recipe_plan_revision(identity, plan_id, revision)` close that. Fixture catalog,
invented prices, authored recipe fixtures; mock orders.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row  # noqa: F401
from test_recipes import (  # noqa: F401  (fixtures are used by name)
    clean_recipes,
    import_fixture,
    match_all,
    meal_products,
    ref,
)
from wsc_support import OTHER_PASSWORD, add_second_buyer, login_headers

from aimo import auth
from aimo.api import create_app
from aimo.db import Problem, connection
from aimo.recipes import scale_recipe
from aimo.schemas import PrepareRequest


def reprice(client, headers, service, connector, pid):
    connector.price_multiplier = Decimal("1.1")
    body = {"proposal_id": pid, "revision": 1, "idempotency_key": str(uuid4())}
    result = client.post(f"/api/purchases/{pid}/confirm", headers=headers, json=body)
    assert result.status_code == 200 and result.json()["status"] == "revised"


def test_the_earlier_revision_of_a_repriced_ready_to_commit_proposal_is_readable(
    service, connector, buyer, agent, request_data
):
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["approval_id"] is None and p["snapshot"]["gross_total"] == "17.00"
    with TestClient(create_app(service)) as client:
        headers = login_headers(client)
        reprice(client, headers, service, connector, p["proposal_id"])
        url = f"/api/purchases/{p['proposal_id']}"
        current = client.get(url).json()
        assert (current["revision"], current["current_revision"]) == (2, 2)
        assert current["snapshot"]["gross_total"] == "18.70"
        first = client.get(url, params={"revision": 1}).json()
        assert (first["revision"], first["current_revision"]) == (1, 2)
        assert first["snapshot"]["gross_total"] == "17.00"
        assert first["fingerprint"] != current["fingerprint"]
        assert first["approval_status"] == "superseded" and first["can_decide"] is False
        assert first["next_action"]["type"] == "view_current_proposal"
        assert first["order_id"] is None and first["proposal_id"] == p["proposal_id"]
        assert client.get(url, params={"revision": 2}).json() == current
        assert client.get(url, params={"revision": 3}).status_code == 404
        assert client.get(url, params={"revision": 0}).status_code == 422
    # The service reads the same revision (no HTTP): other components need not copy totals.
    assert service.get_proposal(buyer, p["proposal_id"], 1)["snapshot"]["gross_total"] == "17.00"
    assert service.get_proposal(buyer, p["proposal_id"])["revision"] == 2


def test_the_earlier_revision_of_an_approval_required_proposal_is_readable_by_revision_too(
    service, connector, buyer, mission
):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, mission)
    with TestClient(create_app(service)) as client:
        headers = login_headers(client)
        reprice(client, headers, service, connector, p["proposal_id"])
        old = client.get(f"/api/purchases/{p['proposal_id']}", params={"revision": 1}).json()
        assert old["snapshot"]["gross_total"] == "1700.00" and old["revision"] == 1
        by_approval = client.get(f"/api/approvals/{p['approval_id']}").json()
        assert by_approval["snapshot"] == old["snapshot"]


def test_another_buyer_cannot_read_any_revision(service, connector, buyer, agent, request_data):
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    add_second_buyer()
    with TestClient(create_app(service)) as owner:
        reprice(owner, login_headers(owner), service, connector, p["proposal_id"])
    with TestClient(create_app(service)) as other:
        login_headers(other, "other-buyer", OTHER_PASSWORD)
        url = f"/api/purchases/{p['proposal_id']}"
        for params in ({}, {"revision": 1}, {"revision": 2}, {"revision": 9}):
            assert other.get(url, params=params).status_code == 404
    with TestClient(create_app(service)) as anonymous:
        assert anonymous.get(url, params={"revision": 1}).status_code == 401


def test_a_recipe_plan_is_readable_by_id_and_revision_inside_the_buyer(
    request, tmp_path, buyer, service
):
    request.getfixturevalue("meal_products")
    actor = auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}
    *_, versions = import_fixture(tmp_path)
    created = scale_recipe(actor, ref(versions))
    final = match_all(actor, created)  # one new plan revision per matched ingredient
    plan_id = final["recipe_plan_id"]
    assert created["recipe_plan_revision"] == 1 and final["recipe_plan_revision"] > 1
    # By ID the current revision; by ID and revision any earlier one, as the agent or the buyer.
    assert service.get_recipe_plan_revision(actor, plan_id) == final
    first = service.get_recipe_plan_revision(buyer, plan_id, 1)
    assert first == created and first["recipe_plan_revision"] == 1
    assert service.get_recipe_plan_revision(buyer, plan_id, final["recipe_plan_revision"]) == final
    assert first != final  # the unmatched first revision differs from the matched final one
    for bad in (0, final["recipe_plan_revision"] + 1, 999):
        with pytest.raises(Problem) as error:
            service.get_recipe_plan_revision(buyer, plan_id, bad)
        assert error.value.status == 404
    other = add_second_buyer()
    with connection() as c:
        stranger = c.execute("SELECT * FROM identities WHERE id='other-buyer'").fetchone()
    assert other and stranger["buyer_id"] != buyer["buyer_id"]
    for revision in (None, 1):
        with pytest.raises(Problem) as error:
            service.get_recipe_plan_revision(stranger, plan_id, revision)
        assert error.value.status == 404
