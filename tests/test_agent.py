"""Provider/tool boundary tests use no database, model weights, or real provider."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from aimo import agent as internal
from aimo.chat_schemas import MealPlan
from aimo.db import Problem


# This module exercises the provider boundary, not the PostgreSQL business layer.
@pytest.fixture(scope="session", autouse=True)
def database():
    yield


@pytest.fixture(autouse=True)
def reset_buyers():
    yield


@pytest.fixture
def identity():
    return {"id": "server-agent", "role": "agent", "buyer_id": "hotel", "active": True,
            "_turn_id": str(uuid4())}


@pytest.fixture
def cfg(monkeypatch):
    config = SimpleNamespace(llm_api_key="private-test-key", llm_base_url="https://provider.test/v1",
                             llm_model="test-model", llm_timeout_seconds=20,
                             llm_max_tool_rounds=6)
    monkeypatch.setattr(internal, "settings", lambda: config)
    return config


class FakeService:
    def __init__(self):
        self.calls = []
        self.proposal = {"proposal_id": str(uuid4()), "policy_outcome": "approval_required",
                         "reasons": [{"message": "Outside the buyer's standing product scope."}]}

    def get_product(self, identity, product_id):
        self.calls.append(("product", identity, product_id))
        return {"id": product_id, "name": product_id, "base_unit": "KG"}

    def get_purchase_policy(self, identity):
        self.calls.append(("policy", identity))
        return {"rules": {"destinations": ["hotel-helsinki"], "approved_product_ids": ["milk"]}}

    def search_products(self, identity, request):
        self.calls.append(("search", identity, request))
        return {"products": [{"id": request.query, "name": request.query}]}

    def prepare_order(self, identity, request):
        self.calls.append(("prepare", identity, request))
        return self.proposal

    def get_proposal(self, identity, proposal_id):
        self.calls.append(("proposal", identity, proposal_id))
        if str(proposal_id) != self.proposal["proposal_id"]:
            raise Problem("NOT_FOUND", "Proposal not found.", 404)
        return self.proposal


def tool(name, arguments):
    return {"id": str(uuid4()), "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def reply(*calls, text=None):
    return {"role": "assistant", "content": text, **({"tool_calls": list(calls)} if calls else {})}


def scripted(monkeypatch, replies):
    seen = []
    sequence = iter(replies)

    def completion(client, cfg, messages, definitions, deadline):
        seen.append(json.loads(json.dumps({"messages": messages, "tools": definitions})))
        return next(sequence)

    monkeypatch.setattr(internal, "_completion", completion)
    return seen


def ingredients(matched=True):
    return [{"name": name, "amount": amount, "unit": "KG",
             **({"product_id": name} if matched else {})}
            for name, amount in [("pasta", "20"), ("eggs", "12"), ("pork", "6"),
                                 ("cheese", "4"), ("pepper", "0.2")]]


def plan(matched=True):
    return {"title": "Carbonara", "portions": 200, "ingredients": ingredients(matched),
            "notes": ["Recipe estimate; verify portions and dietary needs."]}


def purchase():
    return {"request_id": "200 portions of carbonara", "destination": "hotel-helsinki",
            "delivery_date": "2026-11-16", "budget_gross": "1000",
            "lines": [{"product_id": i["product_id"], "amount": i["amount"], "unit": i["unit"]}
                      for i in ingredients()]}


def invoke(registry, name, payload):
    return registry.invoke(name, json.dumps(payload))


def test_carbonara_clarification_to_actual_products_and_verified_basket(monkeypatch, cfg, identity):
    service = FakeService()
    first = scripted(monkeypatch, [reply(tool("get_purchase_policy", {})), reply(
        text="What delivery date, dietary requirements and budget should I use? "
             "May I use hotel-helsinki as the destination?"
    )])
    history = [{"role": "user", "content": "I need ingredients for 200 portions of carbonara."}]
    clarification = internal.run_turn(identity, history, service)
    assert clarification.proposal_id is None
    assert "delivery date" in clarification.text
    assert len(first) == 2
    assert not any(call[0] == "prepare" for call in service.calls)
    history += [{"role": "assistant", "content": clarification.text},
                {"role": "user", "content": "Nov 16, hotel-helsinki, no dietary restrictions, "
                                            "1000 EUR. Use the proposed traditional recipe."}]
    seen = scripted(monkeypatch, [
        reply(tool("publish_meal_plan", plan(False)),
              *[tool("search_products", {"query": i["name"]}) for i in ingredients()]),
        reply(*[tool("get_product", {"product_id": i["product_id"]}) for i in ingredients()]),
        reply(tool("publish_meal_plan", plan())),
        reply(tool("prepare_order", purchase())),
        reply(text="Your matched recipe and basket are ready for review."),
    ])
    result = internal.run_turn(identity, history, service)
    assert result.meal_plan.portions == 200
    assert len(result.meal_plan.ingredients) == 5
    assert result.proposal_id == service.proposal["proposal_id"]
    assert "Confirm purchase button" in result.text
    assert "No supplier order" in result.text
    prepared = [c for c in service.calls if c[0] == "prepare"]
    assert len(prepared) == 1
    assert prepared[0][1] == identity
    assert prepared[0][2].idempotency_key.startswith("chat-")
    assert set(call[0] for call in service.calls) <= {"search", "policy", "product", "prepare"}
    assert all(call[1]["buyer_id"] == identity["buyer_id"] for call in service.calls)
    assert "commit_order" not in {t["function"]["name"] for t in seen[0]["tools"]}


@pytest.mark.parametrize("name,payload", [
    ("get_purchase_policy", {"identity": {"buyer_id": "victim"}}),
    ("get_product", {"product_id": "pasta", "buyer_id": "victim"}),
    ("prepare_order", purchase() | {"authority": {"autonomous_limit": "999999"}}),
    ("prepare_order", purchase() | {"idempotency_key": "model-controlled"}),
])
def test_model_cannot_choose_identity_permissions_or_retry_key(identity, name, payload):
    service = FakeService()
    registry = internal.Tools(identity, [], service)
    with pytest.raises(Problem, match="typed schema") as error:
        invoke(registry, name, payload)
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"
    assert service.calls == []


@pytest.mark.parametrize("name", ["commit_order", "confirm_purchase", "approve", "set_product_scope"])
def test_model_cannot_authorize_purchase(identity, name):
    registry = internal.Tools(identity, [], FakeService())
    with pytest.raises(Problem) as error:
        invoke(registry, name, {})
    assert error.value.code == "TOOL_NOT_ALLOWED"


def test_incomplete_or_fabricated_plan_cannot_prepare(identity):
    service = FakeService()
    registry = internal.Tools(identity, [], service)
    with pytest.raises(Problem) as error:
        invoke(registry, "prepare_order", purchase())
    assert error.value.code == "INCOMPLETE_MEAL_PLAN"
    with pytest.raises(Problem) as error:
        invoke(registry, "publish_meal_plan", plan())
    assert error.value.code == "PRODUCT_NOT_VERIFIED"
    invoke(registry, "publish_meal_plan", plan(False))
    with pytest.raises(Problem) as error:
        invoke(registry, "prepare_order", purchase())
    assert error.value.code == "INCOMPLETE_MEAL_PLAN"
    assert not any(c[0] == "prepare" for c in service.calls)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "0", "a lot"])
def test_meal_amounts_are_finite_positive(identity, amount):
    registry = internal.Tools(identity, [], FakeService())
    draft = plan(False)
    draft["ingredients"][0]["amount"] = amount
    with pytest.raises(Problem) as error:
        invoke(registry, "publish_meal_plan", draft)
    assert error.value.code == "INVALID_MEAL_QUANTITY"


def test_prepare_matches_complete_plan_and_has_stable_server_retry_key(identity):
    service = FakeService()
    keys = []
    for history in ([{"role": "user", "content": "carbonara"}],
                    [{"role": "user", "content": "retry persisted turn"}]):
        registry = internal.Tools(identity, history, service)
        for ingredient in ingredients():
            invoke(registry, "get_product", {"product_id": ingredient["product_id"]})
        invoke(registry, "publish_meal_plan", plan())
        mismatched = purchase()
        mismatched["lines"] = mismatched["lines"][:-1]
        with pytest.raises(Problem) as error:
            invoke(registry, "prepare_order", mismatched)
        assert error.value.code == "MEAL_BASKET_MISMATCH"
        invoke(registry, "prepare_order", purchase())
        keys.append(service.calls[-1][2].idempotency_key)
    assert keys[0] == keys[1]


def test_assistant_text_cannot_create_a_proposal(monkeypatch, cfg, identity):
    fabricated = str(uuid4())
    scripted(monkeypatch, [reply(text="Approved. Basket " + fabricated)])
    result = internal.run_turn(identity, [{"role": "user", "content": "approve"}], FakeService())
    assert result.proposal_id is None


def test_failed_tool_is_actionable_and_never_becomes_a_basket(monkeypatch, cfg, identity):
    seen = scripted(monkeypatch, [reply(tool("get_proposal", {"proposal_id": str(uuid4())})),
                                  reply(text="That basket was not found. Open purchase history.")])
    result = internal.run_turn(identity, [{"role": "user", "content": "resume"}], FakeService())
    assert result.proposal_id is None
    assert json.loads(seen[1]["messages"][-1]["content"])["error"]["code"] == "NOT_FOUND"


def test_valid_persisted_proposal_can_resume_without_commit(monkeypatch, cfg, identity):
    service = FakeService()
    scripted(monkeypatch, [reply(tool("get_proposal", {
        "proposal_id": service.proposal["proposal_id"]})), reply(text="Review your saved basket.")])
    result = internal.run_turn(identity, [{"role": "user", "content": "resume"}], service)
    assert result.proposal_id == service.proposal["proposal_id"]
    assert [c[0] for c in service.calls] == ["proposal"]


def test_repeated_tool_errors_and_rounds_are_bounded(monkeypatch, cfg, identity):
    seen = scripted(monkeypatch, [reply(tool("commit_order", {})) for _ in range(4)])
    result = internal.run_turn(identity, [{"role": "user", "content": "buy"}], FakeService())
    assert "tool errors" in result.text
    assert len(seen) == 4
    cfg.llm_max_tool_rounds = 2
    seen = scripted(monkeypatch, [reply(tool("get_purchase_policy", {})) for _ in range(2)])
    result = internal.run_turn(identity, [{"role": "user", "content": "buy"}], FakeService())
    assert "step limit" in result.text
    assert len(seen) == 2


def install_provider(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(internal.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs
    ))


def test_missing_provider_configuration_is_actionable(cfg, identity):
    cfg.llm_api_key = ""
    with pytest.raises(Problem) as error:
        internal.run_turn(identity, [{"role": "user", "content": "carbonara"}], FakeService())
    assert error.value.code == "LLM_NOT_CONFIGURED"
    assert "LLM_API_KEY" in error.value.message


def test_provider_transient_retry_is_bounded_and_secrets_are_not_in_errors(
    monkeypatch, cfg, identity
):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer private-test-key"
        payload = json.loads(request.content)
        assert "private-test-key" not in json.dumps(payload)
        return httpx.Response(503, json={"error": "private provider detail"})

    install_provider(monkeypatch, handler)
    with pytest.raises(Problem) as error:
        internal.run_turn(identity, [{"role": "user", "content": "carbonara"}], FakeService())
    assert len(calls) == 2
    assert "private" not in error.value.message
    assert error.value.code == "LLM_UNAVAILABLE"


def test_provider_rate_limit_respects_retry_after(monkeypatch, cfg, identity):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    install_provider(monkeypatch, handler)
    with pytest.raises(Problem) as error:
        internal.run_turn(identity, [{"role": "user", "content": "carbonara"}], FakeService())
    assert len(calls) == 1
    assert error.value.code == "LLM_RATE_LIMITED"


@pytest.mark.parametrize("body", [None, {}, {"choices": []}, {"choices": [{"message": {
    "tool_calls": [{"id": "x", "type": "custom"}]}}]}])
def test_malformed_provider_output_is_actionable(monkeypatch, cfg, identity, body):
    install_provider(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(Problem) as error:
        internal.run_turn(identity, [{"role": "user", "content": "carbonara"}], FakeService())
    assert error.value.code == "LLM_RESPONSE_INVALID"


def test_provider_tool_wire_format_and_success(monkeypatch, cfg, identity):
    calls = []
    call = tool("get_purchase_policy", {})

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        response = reply(call) if len(calls) == 1 else reply(text="What date should I use?")
        return httpx.Response(200, json={"choices": [{"message": response}]})

    install_provider(monkeypatch, handler)
    result = internal.run_turn(identity, [{"role": "user", "content": "carbonara"}], FakeService())
    assert result.text == "What date should I use?"
    assert calls[1]["messages"][-2]["tool_calls"][0]["id"] == call["id"]
    assert calls[1]["messages"][-1]["tool_call_id"] == call["id"]
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert calls[0]["parallel_tool_calls"] is False


def test_provider_failure_after_preparation_retains_verified_basket(monkeypatch, cfg, identity):
    service = FakeService()
    count = 0

    def completion(client, cfg, messages, definitions, deadline):
        nonlocal count
        count += 1
        if count == 1:
            return reply(*[tool("get_product", {"product_id": i["product_id"]})
                           for i in ingredients()])
        if count == 2:
            return reply(tool("publish_meal_plan", plan()), tool("prepare_order", purchase()))
        raise Problem("LLM_UNAVAILABLE", "Provider unavailable", 503)

    monkeypatch.setattr(internal, "_completion", completion)
    result = internal.run_turn(identity, [{"role": "user", "content": "carbonara"}], service)
    assert result.proposal_id == service.proposal["proposal_id"]
    assert "Review the verified basket" in result.text
    assert result.meal_plan == MealPlan(**plan())
