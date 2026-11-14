"""CNF-034 / CNF-035 over HTTP: the orders list and cancelling a pending request.

Session cookie plus CSRF and Origin like the other write routes; buyer-scoped; the response
shapes are declared in OpenAPI. Fixture catalog and invented prices; mock orders only.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_http import login

from aimo.api import create_app
from aimo.schemas import CommitRequest, PrepareRequest


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


@pytest.fixture
def pending(service, agent, request_data):
    return service.prepare_order(agent, PrepareRequest(**request_data))


def test_the_orders_list_needs_a_session(http):
    assert http.get("/api/orders").status_code == 401


def test_the_orders_list_shows_the_pending_request_in_the_declared_shape(http, pending):
    login(http)
    body = http.get("/api/orders").json()
    assert body["next_offset"] is None and body["total"] == 1
    item = body["items"][0]
    assert item["status"] == "pending" and item["proposal_id"] == pending["proposal_id"]
    assert set(item) == {
        "status",
        "title",
        "scheduled_for",
        "proposal_id",
        "order_id",
        "schedule_id",
        "gross_total",
        "currency",
        "line_count",
        "line_names",
        "cancel_reason",
        "placed_at",
        "fulfilment",
        "paused",
        "schedule_title",
        "updated_at",
    }


def test_paging_parameters_are_bounded(http, pending):
    login(http)
    assert http.get("/api/orders?limit=0").status_code == 422
    assert http.get("/api/orders?limit=51").status_code == 422
    assert http.get("/api/orders?offset=-1").status_code == 422
    assert http.get("/api/orders?offset=0&limit=1").status_code == 200


def test_a_placed_order_is_listed_as_placed_and_links_its_order(http, service, buyer, pending):
    receipt = service.commit_order(
        buyer,
        CommitRequest(
            proposal_id=pending["proposal_id"],
            revision=pending["revision"],
            idempotency_key=str(uuid4()),
        ),
    )
    login(http)
    item = http.get("/api/orders").json()["items"][0]
    assert item["status"] == "placed" and item["order_id"] == receipt["order_id"]


def test_cancelling_a_pending_request_needs_csrf_and_origin(http, pending):
    headers = login(http)
    url = f"/api/purchases/{pending['proposal_id']}/cancel"
    assert http.post(url).status_code == 403
    bad = headers | {"Origin": "https://evil.invalid"}
    assert http.post(url, headers=bad).status_code == 403
    assert http.post(url, headers=headers | {"X-CSRF-Token": "wrong"}).status_code == 403
    assert http.get("/api/orders").json()["items"][0]["status"] == "pending"


def test_cancelling_a_pending_request_lists_it_as_cancelled_and_is_idempotent(http, pending):
    headers = login(http)
    url = f"/api/purchases/{pending['proposal_id']}/cancel"
    first = http.post(url, headers=headers)
    assert first.status_code == 200
    assert first.json()["reason"] == "customer_cancelled"
    assert set(first.json()) == {"proposal_id", "reason", "cancelled_by", "cancelled_at"}
    assert http.post(url, headers=headers).json() == first.json()
    item = http.get("/api/orders").json()["items"][0]
    assert item["status"] == "cancelled" and item["cancel_reason"] == "customer_cancelled"
    confirm = http.post(
        f"/api/purchases/{pending['proposal_id']}/confirm",
        headers=headers,
        json={
            "proposal_id": pending["proposal_id"],
            "revision": pending["revision"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert confirm.status_code == 409 and confirm.json()["error"]["code"] == "REQUEST_CANCELLED"


def test_a_placed_order_cannot_be_cancelled_over_http(http, service, buyer, pending):
    service.commit_order(
        buyer,
        CommitRequest(
            proposal_id=pending["proposal_id"],
            revision=pending["revision"],
            idempotency_key=str(uuid4()),
        ),
    )
    headers = login(http)
    response = http.post(f"/api/purchases/{pending['proposal_id']}/cancel", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_ALREADY_PLACED"


def test_an_unknown_or_malformed_id_is_refused(http):
    headers = login(http)
    assert http.post(f"/api/purchases/{uuid4()}/cancel", headers=headers).status_code == 404
    assert http.post("/api/purchases/not-a-uuid/cancel", headers=headers).status_code == 422


def test_openapi_declares_the_routes_and_their_models(http):
    paths = (
        http.get("/openapi.json").json()["paths"]
        if http.get("/openapi.json").status_code == 200
        else None
    )
    if paths is None:  # the app may hide the schema; read it from the app object
        paths = http.app.openapi()["paths"]
    assert "get" in paths["/api/orders"]
    assert "post" in paths["/api/purchases/{proposal_id}/cancel"]
    schemas = http.app.openapi()["components"]["schemas"]
    assert {"OrderListItem", "OrdersResponse", "CancellationResponse"} <= set(schemas)
    assert schemas["OrderListItem"]["properties"]["status"]["enum"] == [
        "scheduled",
        "pending",
        "placed",
        "cancelled",
    ]


def test_the_status_filter_and_total_over_http(http, service, buyer, pending):
    service.commit_order(
        buyer,
        CommitRequest(
            proposal_id=pending["proposal_id"],
            revision=pending["revision"],
            idempotency_key=str(uuid4()),
        ),
    )
    login(http)
    everything = http.get("/api/orders").json()
    assert everything["total"] == 1
    placed = http.get("/api/orders?status=placed").json()
    assert [i["status"] for i in placed["items"]] == ["placed"] and placed["total"] == 1
    assert placed["items"][0]["placed_at"]
    assert http.get("/api/orders?status=pending").json() == {
        "items": [],
        "next_offset": None,
        "total": 0,
    }
    both = http.get("/api/orders?status=pending,placed").json()
    assert both["total"] == 1
    assert http.get("/api/orders?status=").json()["total"] == 1  # empty means everything


def test_an_unknown_status_filter_is_a_clear_422(http):
    login(http)
    response = http.get("/api/orders?status=placed,shipped")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ORDER_STATUS"
    assert "shipped" in response.json()["error"]["message"]
