"""Actual purchasing functions with PostgreSQL and authored meal/supplier fixtures.

The standalone agent workstream predates the backend route migration, so this
module runs after that dependency is integrated. The provider alone is scripted.
"""

import json
import os
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("aimo.conversations", reason="requires the chat backend integration")

from aimo import agent as internal
from aimo import auth, fixtures
from aimo.api import create_app
from aimo.db import Problem, close_pools, connection, fingerprint
from aimo.ingest import publish
from aimo.schemas import CommitRequest
from aimo.service import Service
from aimo.upstream import FixtureClient
from aimo.worker import run_once

INGREDIENTS = [("pasta", "20"), ("eggs", "12"), ("pork", "6"), ("cheese", "4"), ("pepper", "0.2")]


def call(name, arguments):
    return {"id": str(uuid4()), "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def tool_reply(*calls):
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def test_carbonara_actual_catalog_policy_customer_confirmation_and_persisted_receipt(
    monkeypatch, buyer
):
    # These are authored fixture projections, never described as sponsor/live data.
    original = fixtures.fixture_facts()
    meal_products = []
    for name, _ in INGREDIENTS:
        p = deepcopy(original[0])
        p.update(id="meal-" + name, name="Authored carbonara " + name,
                 names={"en": "Authored carbonara " + name}, sales_unit="KG", base_unit="KG",
                 units={"KG": "1"}, order_step="0.01", variable_weight=False, claims=[],
                 allergens={"AE": "CONTAINS"} if name == "eggs" else
                 {"AM": "CONTAINS"} if name == "cheese" else {},
                 measures={"KG": {"value": "1", "status": "known", "basis": ["authored.fixture"]},
                           "L": {"value": None, "status": "unknown", "basis": []}},
                 provenance={"source": "authored meal fixture", "product_id": "meal-" + name})
        meal_products.append(p)
    monkeypatch.setattr(fixtures, "fixture_facts", lambda: original + meal_products)
    facts = original + meal_products
    publish(facts, "authored-carbonara-test", fingerprint(facts))
    config = SimpleNamespace(llm_api_key="unused-scripted-provider", llm_base_url="https://unused.test",
                             llm_model="scripted", llm_timeout_seconds=20, llm_max_tool_rounds=20)
    monkeypatch.setattr(internal, "settings", lambda: config)
    delivery = str(date.today() + timedelta(days=2))
    plan = {"title": "Traditional carbonara (authored recipe estimate)", "portions": 200,
            "ingredients": [{"name": name, "amount": amount, "unit": "KG",
                             "product_id": "meal-" + name} for name, amount in INGREDIENTS],
            "notes": ["Contains egg, milk and gluten; customer requested no dietary restrictions."]}
    prepared = {"request_id": "200 portions carbonara", "destination": "hotel-helsinki",
                "delivery_date": delivery, "budget_gross": "1000", "requirements": {},
                "lines": [{"product_id": i["product_id"], "amount": i["amount"], "unit": i["unit"]}
                          for i in plan["ingredients"]]}
    sequence = iter([
        tool_reply(call("get_purchase_policy", {})),
        {"role": "assistant", "content": "What delivery date, dietary needs and budget? "
         "Can I deliver to hotel-helsinki? Traditional carbonara contains egg, milk and gluten."},
        tool_reply(*[call("search_products", {"query": name}) for name, _ in INGREDIENTS]),
        tool_reply(*[call("get_product", {"product_id": "meal-" + name})
                     for name, _ in INGREDIENTS]),
        tool_reply(call("publish_meal_plan", plan)),
        tool_reply(call("prepare_order", prepared)),
        {"role": "assistant", "content": "Review the full ingredient basket and confirm in the product."},
    ])
    seen = []

    def provider(client, cfg, messages, definitions, deadline):
        seen.append(deepcopy(messages))
        return next(sequence)

    monkeypatch.setattr(internal, "_completion", provider)
    connector = FixtureClient()
    service = Service(connector)
    with TestClient(create_app(service)) as client:
        signed = client.post("/api/login", headers={"Origin": "http://testserver"},
                             json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]})
        assert signed.status_code == 200, signed.text
        headers = {"Origin": "http://testserver", "X-CSRF-Token": signed.json()["csrf_token"]}
        created = client.post("/api/conversations", headers=headers,
                              json={"title": "Carbonara for 200", "idempotency_key": str(uuid4())})
        assert created.status_code == 200, created.text
        cid = created.json()["id"]
        message_url = f"/api/conversations/{cid}/messages"
        first = client.post(message_url, headers=headers, json={
            "text": "I need ingredients for 200 portions of carbonara.", "idempotency_key": str(uuid4())})
        assert first.status_code == 200, first.text
        assert first.json()["busy"] is True
        assert run_once(service)
        first = client.get(f"/api/conversations/{cid}")
        assert "delivery date" in first.json()["messages"][-1]["text"]
        assert first.json()["purchases"] == []
        second_body = {"text": f"{delivery}, hotel-helsinki, no dietary restrictions, 1000 EUR. "
                       "Use the traditional carbonara recipe with pasta, eggs, pork, cheese and pepper.",
                       "idempotency_key": str(uuid4())}
        second = client.post(message_url, headers=headers, json=second_body)
        assert second.status_code == 200, second.text
        assert second.json()["busy"] is True
        assert run_once(service)
        second = client.get(f"/api/conversations/{cid}")
        data = second.json()
        assert data["messages"][-1]["meal_plan"]["portions"] == 200
        basket = data["purchases"][0]
        assert len(basket["snapshot"]["lines"]) == 5
        assert basket["snapshot"]["gross_total"] == "71.74"
        assert {i["product_id"] for i in basket["snapshot"]["lines"]} == {
            "meal-" + name for name, _ in INGREDIENTS}
        assert all(i["quantity"]["status"] == "derived" for i in basket["snapshot"]["lines"])
        assert basket["policy_outcome"] == "approval_required"
        assert {r["code"] for r in basket["reasons"]} >= {
            "SUBSTITUTION_REQUIRES_APPROVAL", "AUTONOMOUS_LIMIT_EXCEEDED"}
        assert basket["order_id"] is None
        with connection() as c:
            current_scope = c.execute("SELECT rules FROM policies WHERE buyer_id=%s ORDER BY version DESC",
                                      (buyer["buyer_id"],)).fetchone()["rules"]["approved_product_ids"]
            assert current_scope == ["464306"]  # A recipe never grants standing product authority.
            assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
        # Duplicate chat submission resumes persisted state without invoking the provider again.
        assert client.post(message_url, headers=headers, json=second_body).json() == data
        assert len(seen) == 7
        actor = auth.internal_agent(buyer)
        commit = CommitRequest(proposal_id=basket["proposal_id"], revision=basket["revision"],
                               idempotency_key=str(uuid4()))
        with pytest.raises(Problem) as error:
            service.commit_order(actor, commit)
        assert error.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"
        confirm_url = f"/api/purchases/{basket['proposal_id']}/confirm"
        payload = commit.model_dump(mode="json")
        assert client.post(confirm_url, json=payload).status_code == 403
        confirmed = client.post(confirm_url, headers=headers, json=payload)
        assert confirmed.status_code == 200, confirmed.text
        receipt = confirmed.json()
        assert receipt["status"] == "accepted_mock"
        assert receipt["upstream_order_placed"] is False and receipt["inventory_reserved"] is False
        # A new process-level pool reads the same conversation, decision and receipt.
        close_pools()
        connector.lookup = lambda *args: (_ for _ in ()).throw(AssertionError("saved retry needs no supplier"))
        assert client.post(confirm_url, headers=headers, json=payload).json() == receipt
        refreshed = client.get(f"/api/conversations/{cid}")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["purchases"][0]["order_id"] == receipt["order_id"]
        sequence = iter([
            tool_reply(call("get_order", {"order_id": receipt["order_id"]})),
            {"role": "assistant", "content": "The saved receipt is accepted by the demo service. "
             "No supplier order was placed."},
        ])
        resumed = client.post(message_url, headers=headers, json={
            "text": "Was my confirmed basket recorded?", "idempotency_key": str(uuid4())})
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["busy"] is True
        assert run_once(service)
        resumed = client.get(f"/api/conversations/{cid}")
        assert "accepted_mock" in str(seen[-2])
        assert "No supplier order" in resumed.json()["messages"][-1]["text"]
        with connection() as c:
            assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 1
            assert c.execute("SELECT count(*) AS n FROM customer_confirmations").fetchone()["n"] == 1
    # Leave other modules on their usual fixture catalog if this test joins the full suite.
    publish(original, "restore-standard-fixtures", fingerprint(original))
