"""CNF-017 (browser side): GET /api/purchases/{proposal_id}/receipt returns the stored receipt.

A thin pass-through to the stored `orders.receipt` for the signed-in buyer's own proposal.
Fixture catalog and invented prices; the order is the demo service's mock acceptance.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
from wsc_support import OTHER_PASSWORD, add_second_buyer, counts, login_headers

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.api import create_app
from aimo.schemas import CommitRequest, OrderResponse, PrepareRequest


def ordered(service, buyer, request_data):
    actor = auth.internal_agent(buyer)
    p = service.prepare_order(actor, PrepareRequest.model_validate(request_data))
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    return p, conversations.confirm(buyer, p["proposal_id"], body, service)


def test_the_stored_receipt_is_returned_for_an_ordered_proposal(service, buyer, request_data):
    p, receipt = ordered(service, buyer, request_data)
    with TestClient(create_app(service)) as client:
        login_headers(client)
        response = client.get(f"/api/purchases/{p['proposal_id']}/receipt")
        assert response.status_code == 200, response.text
        stored = response.json()
        # The route serializes through OrderResponse (timestamps as ...Z), same as the confirm route.
        derived = {"delivery_date", "destination", "fulfilment"}  # added on read (JNP3-FUL)
        assert {k: v for k, v in stored.items() if k not in derived} == {
            k: v
            for k, v in OrderResponse.model_validate(receipt).model_dump(mode="json").items()
            if k not in derived
        }
        assert stored["label"] == "Accepted by demo order service"
        assert stored["upstream_order_placed"] is False and stored["inventory_reserved"] is False
        # It is a read: a second GET changes nothing and returns the same body.
        assert client.get(f"/api/purchases/{p['proposal_id']}/receipt").json() == stored
    assert workflow.get_order(auth.internal_agent(buyer), receipt["order_id"]) == receipt


def test_a_proposal_without_an_order_has_no_receipt(service, buyer, request_data):
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    before = counts()
    with TestClient(create_app(service)) as client:
        login_headers(client)
        response = client.get(f"/api/purchases/{p['proposal_id']}/receipt")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NO_RECEIPT"
        assert client.get(f"/api/purchases/{uuid4()}/receipt").status_code == 404
    assert counts() == before


def test_the_receipt_needs_a_session_and_stays_inside_the_buyer(service, buyer, request_data):
    p, _ = ordered(service, buyer, request_data)
    add_second_buyer()
    path = f"/api/purchases/{p['proposal_id']}/receipt"
    with TestClient(create_app(service)) as anonymous:
        assert anonymous.get(path).status_code == 401
    with TestClient(create_app(service)) as other:
        login_headers(other, "other-buyer", OTHER_PASSWORD)
        response = other.get(path)
        # The same answer as an unknown id: another buyer's order is not even confirmed to exist.
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
