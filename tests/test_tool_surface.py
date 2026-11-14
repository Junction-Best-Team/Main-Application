"""JNP3-TCT-001, 002, 003 and 005: the agent tool surface (Approved: 003, 005; Draft: 001, 002).

Everything is hermetic: fixture catalog, fixture embeddings, `FixtureClient` supplier terms
(invented prices and stock, labelled `mode: fixture`), no network and no LLM. The tools are
driven through `ToolSession.invoke` exactly as the runner does (a JSON string of arguments).

Tests marked `xfail(strict=True)` record a gap that exists on `origin/develop` 837dfdf. When the
gap is closed the test XPASSes, strict mode fails the run and the marker must be removed.
Verify a gap with `pytest --runxfail <file>`: the failure must be the one named in `reason`.
"""

import dataclasses
import json
import re
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_recipes import import_fixture, meal_products  # noqa: F401  (fixture re-use, person 2's)

from aimo import agent as runner
from aimo.agent_provider import AssistantReply, ChatProvider
from aimo.agent_tools import ToolSession
from aimo.db import Problem
from aimo.guardrails import project
from aimo.recipe_schemas import MatchIngredient
from aimo.schemas import CommitRequest

IDENTITY = {"id": "a", "buyer_id": "b", "_turn_id": "t"}
FORBIDDEN_WORDS = re.compile(r"approve|confirm|commit|reject|policy_edit|set_|grant", re.I)
# What must never come back to the agent in an error: connection strings, traces, raw driver text.
LEAKS = re.compile(r"postgres(ql)?://|password|traceback|File \"|psycopg|api[_-]?key|secret", re.I)


def build(service=None):
    """A ToolSession; the recipe tools are always registered (PR #103 removed the flag)."""
    return ToolSession(dict(IDENTITY), service)


def registry():
    """The tools exactly as ToolSession registers them."""
    return build().registry


ALL_TOOLS = sorted(registry())
RECIPE_TOOLS = [
    "get_recipe",
    "get_recipe_plan",
    "match_ingredient",
    "match_ingredients",
    "scale_recipe",
    "search_recipes",
]


class NoService:
    """An invalid call must be rejected before any purchasing function is reached."""

    def __getattr__(self, name):
        raise AssertionError("service." + name + " was reached by an invalid call")


@pytest.fixture
def actor(agent):
    return agent | {"_turn_id": str(uuid4())}


@pytest.fixture
def session(actor, service):
    return ToolSession(actor, service)


@pytest.fixture
def delivery():
    return str(date.today() + timedelta(days=2))


def call(session, name, arguments):
    return session.invoke(name, arguments if isinstance(arguments, str) else json.dumps(arguments))


def rejected(session, name, arguments):
    with pytest.raises(Problem) as error:
        call(session, name, arguments)
    return error.value


def assert_agent_safe(problem):
    """What the runner returns to the model: a code, a message and no internals."""
    assert problem.code and problem.code == problem.code.upper()
    assert problem.message.strip()
    assert not LEAKS.search(problem.code + " " + problem.message), problem.message


# ----------------------------------------------------------------- TCT-001 / TCT-002 (Draft)


def test_the_full_tool_list_is_always_exposed():
    """Purchasing, recipe and explicit memory tools are always registered."""
    memory_tools = {"search_memory", "manage_memory"}
    assert len(ALL_TOOLS) == 17, ALL_TOOLS
    assert set(RECIPE_TOOLS) | memory_tools <= set(ALL_TOOLS)
    assert len(set(ALL_TOOLS) - set(RECIPE_TOOLS) - memory_tools) == 9


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct001_every_tool_is_typed_and_documented(name):
    """C5 acceptance check: name, description, closed JSON schema; no human-authority tool."""
    tool = registry()[name]
    definition = tool.schema(name)
    assert definition["type"] == "function" and definition["function"]["name"] == name
    assert len(definition["function"]["description"].strip()) >= 20
    parameters = definition["function"]["parameters"]
    assert parameters["type"] == "object" and parameters["additionalProperties"] is False
    for field, schema in parameters.get("properties", {}).items():
        assert {"type", "$ref", "anyOf", "enum", "allOf"} & schema.keys(), (name, field)
    assert not FORBIDDEN_WORDS.search(name), "a registered tool must not carry human authority"


def test_tct002_each_tool_has_its_own_input_model():
    models = [tool.request for tool in registry().values()]
    assert len(models) == len(set(models)), "two tools share one input model class"


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct002_each_input_model_has_an_example(name):
    schema = registry()[name].request.model_json_schema()
    assert schema.get("examples"), name + " has no example in its input schema"


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct002_every_example_is_valid_input_for_its_own_tool(name):
    request = registry()[name].request
    for example in request.model_json_schema()["examples"]:
        request.model_validate(example)  # an example the tool would reject is worse than none


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct002_each_tool_declares_one_output_model(name):
    spec = registry()[name]
    declared = {f.name for f in dataclasses.fields(spec)} & {"response", "output", "result"}
    assert declared, name + " declares no output model"


# ------------------------------------------------------------- TCT-003 (Approved): input errors

NON_OBJECT_PAYLOADS = ["not json at all", "[]", "null", '"text"', "42", "", "{"]


@pytest.mark.parametrize("payload", NON_OBJECT_PAYLOADS, ids=lambda p: repr(p)[:12])
@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct003_non_object_arguments_are_rejected_with_a_code(name, payload):
    problem = rejected(build(NoService()), name, payload)
    assert problem.code == "INVALID_TOOL_ARGUMENTS" and problem.status == 422
    assert_agent_safe(problem)


@pytest.mark.parametrize(
    "extra",
    [
        {"unexpected_field": 1},
        {"buyer_id": "victim", "agent_id": "victim"},
        {"idempotency_key": "model-chosen-key"},
        {"approved": True, "authority": {"autonomous_limit": "999999"}},
    ],
    ids=["unknown", "identity", "retry-key", "authority"],
)
@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct003_unknown_fields_are_rejected_before_any_service_call(name, extra):
    problem = rejected(build(NoService()), name, extra)
    assert problem.code == "INVALID_TOOL_ARGUMENTS" and problem.status == 422
    assert_agent_safe(problem)


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct003_wrong_type_in_each_field_is_rejected(name):
    properties = registry()[name].request.model_json_schema().get("properties", {})
    assert properties or name == "get_purchase_policy"
    for field in properties:
        # A dict is not a valid str, int, date, UUID, Decimal, list or closed sub-model value.
        problem = rejected(build(NoService()), name, {field: {"bad": 1}})
        assert problem.code == "INVALID_TOOL_ARGUMENTS", (name, field)
        assert_agent_safe(problem)


def test_tct003_missing_required_fields_and_range_violations_are_rejected():
    session = build(NoService())
    cases = [
        ("get_product", {}),
        ("get_product", {"product_id": ""}),
        ("get_product", {"product_id": "x" * 41}),
        ("search_products", {"query": ""}),
        ("search_products", {"query": "milk", "limit": 21}),
        ("search_products", {"query": "milk", "requirements": {"vegan": True}}),
        ("check_price_and_availability", {"product_ids": [], "delivery_date": "2026-11-20"}),
        ("check_price_and_availability", {"product_ids": ["1"], "delivery_date": "20-11-2026"}),
        ("get_proposal", {"proposal_id": "not-a-uuid"}),
        ("get_order", {}),
        ("publish_meal_plan", {"title": "t", "portions": 0, "ingredients": []}),
        (
            "prepare_order",
            {
                "request_id": "r",
                "destination": "d",
                "delivery_date": "2026-11-20",
                "lines": [{"product_id": "1", "amount": "-1", "unit": "L"}],
            },
        ),
        (
            "prepare_order",
            {
                "request_id": "r",
                "destination": "d",
                "delivery_date": "2026-11-20",
                "lines": [{"product_id": "1", "amount": "1", "unit": "L"}] * 2,
            },
        ),
        ("scale_recipe", {"recipe_id": "r", "version": "v", "portions": 0}),
        ("get_recipe_plan", {"plan_id": "zz"}),
        ("match_ingredient", {"plan_id": str(uuid4()), "revision": 0, "ingredient_id": "i"}),
        ("match_ingredients", {"plan_id": str(uuid4()), "revision": 1, "matches": []}),
    ]
    assert {name for name, _ in cases} <= set(ALL_TOOLS)
    for name, arguments in cases:
        problem = rejected(session, name, arguments)
        assert problem.code == "INVALID_TOOL_ARGUMENTS" and problem.status == 422, (name, arguments)
        assert_agent_safe(problem)


def test_tct003_unregistered_tool_names_are_refused_with_the_customer_route():
    session = build(NoService())
    for name in ("commit_order", "approve", "confirm_purchase", "set_product_scope", "nope"):
        problem = rejected(session, name, "{}")
        assert problem.code == "TOOL_NOT_ALLOWED" and problem.status == 422
        assert "confirmation" in problem.message  # tells the agent where the human step lives
        assert_agent_safe(problem)


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_tct003_invalid_argument_message_names_the_field_to_correct(name):
    properties = registry()[name].request.model_json_schema().get("properties", {})
    field = next(iter(properties), "unexpected_field")
    problem = rejected(build(NoService()), name, {field: {"bad": 1}})
    assert field in problem.message, problem.message


# ------------------------------------------------------- TCT-003: failures after valid input


def test_tct003_unknown_records_return_a_code_and_say_what_was_missing(session):
    for name, arguments in [
        ("get_product", {"product_id": "does-not-exist"}),
        ("get_proposal", {"proposal_id": str(uuid4())}),
        ("get_order", {"order_id": str(uuid4())}),
        ("get_recipe_plan", {"plan_id": str(uuid4())}),
    ]:
        problem = rejected(session, name, arguments)
        assert problem.code == "NOT_FOUND" and problem.status == 404, name
        assert_agent_safe(problem)
        assert "not found" in problem.message.lower()


def test_tct003_workflow_precondition_errors_say_which_tool_to_use_first(session, delivery):
    problem = rejected(
        session,
        "prepare_order",
        {
            "request_id": "r1",
            "destination": "hotel-helsinki",
            "delivery_date": delivery,
            "lines": [{"product_id": "464306", "amount": "1", "unit": "L"}],
        },
    )
    assert problem.code == "INCOMPLETE_MEAL_PLAN" and "Match every ingredient" in problem.message
    plan = {
        "title": "Milk",
        "portions": 1,
        "ingredients": [{"name": "milk", "amount": "1", "unit": "L", "product_id": "464306"}],
    }
    problem = rejected(session, "publish_meal_plan", plan)
    assert problem.code == "PRODUCT_NOT_VERIFIED" and "get_product" in problem.message
    problem = rejected(
        session,
        "match_ingredient",
        {"plan_id": str(uuid4()), "revision": 1, "ingredient_id": "i", "product_id": "464306"},
    )
    assert problem.code == "PRODUCT_NOT_VERIFIED" and "get_product" in problem.message
    problem = rejected(
        session,
        "match_ingredients",
        {
            "plan_id": str(uuid4()),
            "revision": 1,
            "matches": [{"ingredient_id": "i", "product_id": "464306"}],
        },
    )
    assert problem.code == "PRODUCT_NOT_VERIFIED" and "get_product" in problem.message


NUL = "\u0000"


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_product", {"product_id": "a" + NUL + "b"}),
        ("search_products", {"query": "mi" + NUL + "lk"}),
        (
            "check_price_and_availability",
            {"product_ids": ["a" + NUL + "b"], "delivery_date": "2030-01-01"},
        ),
    ],
    ids=["get_product", "search_products", "check_price_and_availability"],
)
def test_tct003_nul_byte_arguments_become_a_correctable_error(session, name, arguments):
    problem = rejected(session, name, arguments)  # a raw DataError is not a Problem: fails here
    assert problem.status < 500
    assert_agent_safe(problem)


def test_tct003_out_of_range_delivery_date_is_not_reported_as_retry_later(session):
    try:
        call(
            session,
            "check_price_and_availability",
            {"product_ids": ["464306"], "delivery_date": "0001-01-01"},
        )
    except Problem as problem:
        assert (
            problem.code != "TOOL_RESULT_INVALID" and "retry later" not in problem.message.lower()
        )


@pytest.fixture
def recipe_data(tmp_path, meal_products, actor):  # noqa: F811
    # Not truncated here: `meal_products` has already stored its product evidence.
    *_, versions = import_fixture(tmp_path)
    return versions


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("search_recipes", {"query": "car" + NUL + "bonara"}),
        ("get_recipe", {"recipe_id": "r" + NUL, "version": "v"}),
    ],
    ids=["search_recipes", "get_recipe"],
)
def test_tct003_nul_byte_recipe_arguments_become_a_correctable_error(
    session, recipe_data, name, arguments
):
    problem = rejected(session, name, arguments)
    assert problem.status < 500


def test_tct003_recipe_tools_return_codes_for_unknown_ids(session, recipe_data):
    for name, arguments in [
        ("get_recipe", {"recipe_id": "unknown", "version": "v"}),
        ("scale_recipe", {"recipe_id": "unknown", "version": "v", "portions": 2}),
    ]:
        problem = rejected(session, name, arguments)
        assert problem.code == "NOT_FOUND" and problem.status == 404
        assert_agent_safe(problem)


# --------------------------------------------- TCT-003: what the runner hands back to the model


def drive(monkeypatch, identity, service, calls):
    """Run the real runner with a scripted provider; return (turn or error, tool messages)."""
    script = iter(
        [
            {"role": "assistant", "content": None, "tool_calls": calls},
            {"role": "assistant", "content": "Understood."},
        ]
    )
    seen = []

    def complete(self, history, tools, deadline):
        seen.append(json.loads(json.dumps(history, default=str)))
        return AssistantReply.model_validate(next(script))

    cfg = SimpleNamespace(
        llm_api_key="private-provider-key",
        llm_base_url="https://provider.test/v1",
        llm_model="test-model",
        llm_timeout_seconds=20,
        llm_max_tool_rounds=4,
    )
    monkeypatch.setattr(runner, "settings", lambda: cfg)
    monkeypatch.setattr(ChatProvider, "complete", complete)
    messages = [{"role": "user", "content": "hello"}]
    try:
        outcome = runner.run_turn(identity, messages, service, budget_seconds=30)
    except Problem as problem:
        outcome = problem
    tool_messages = [m for history in seen[-1:] for m in history if m["role"] == "tool"]
    return outcome, tool_messages


def tool_call(name, arguments):
    return {
        "id": str(uuid4()),
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def test_tct003_runner_returns_the_error_envelope_for_a_malformed_call(monkeypatch, actor, service):
    outcome, messages = drive(
        monkeypatch, actor, service, [tool_call("get_product", '{"product_id": 7}')]
    )
    assert not isinstance(outcome, Problem) and len(messages) == 1
    envelope = json.loads(messages[0]["content"])
    assert envelope["purchase_authorized"] is False
    assert envelope["error"]["code"] == "INVALID_TOOL_ARGUMENTS" and envelope["error"]["message"]
    assert set(envelope["error"]) == {"code", "message"}
    assert not LEAKS.search(messages[0]["content"])


def test_tct003_runner_survives_a_database_rejected_argument(monkeypatch, actor, service):
    outcome, messages = drive(
        monkeypatch, actor, service, [tool_call("get_product", json.dumps({"product_id": "a\0b"}))]
    )
    assert not isinstance(outcome, Problem), getattr(outcome, "code", None)
    assert json.loads(messages[0]["content"])["error"]["code"]


# ----------------------------------------------------------- TCT-005 (Approved): evidence + units


def assert_product_evidence_and_units(product):
    assert product["sales_unit"] and product["base_unit"]
    assert product["sales_unit"] in product["units"], "sales unit has no conversion factor"
    assert product["units"] and all(Decimal_like(v) for v in product["units"].values())
    assert product["provenance"]["source"] and product["provenance"]["product_id"] == product["id"]
    assert product["order_step"] is not None
    for code, measure in product["measures"].items():
        assert code in ("L", "KG"), code  # the measure keys are the unit codes
        assert measure["status"] in ("known", "unknown", "conflicting")
        if measure["status"] == "known":
            assert measure["value"] is not None and measure["basis"], (code, measure)


def Decimal_like(value):  # noqa: N802 - tiny local predicate
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def assert_quantity_has_unit_and_basis(quantity):
    assert quantity["requested_unit"] and quantity["sales_unit"] and quantity["source_step"]
    assert quantity["requested_amount"] and quantity["status"]
    if quantity["status"] == "derived":
        assert quantity["basis"] and quantity["sales_quantity"] is not None


def test_tct005_search_products_results_carry_evidence_and_units(session):
    result = call(session, "search_products", {"query": "milk", "limit": 5})
    assert result["products"] and result["generation"] and result["model"] and result["strategy"]
    for product in result["products"]:
        assert_product_evidence_and_units(product)
        assert product["match_is_suitability_proof"] is False


def test_tct005_get_product_result_carries_evidence_and_units(session):
    product = call(session, "get_product", {"product_id": "464306"})
    assert_product_evidence_and_units(product)
    for key in ("packaging", "deposits", "substitutions", "allergen_conflicts", "conflicts"):
        assert key in product  # original supplier declarations are passed through, not summarised


def test_tct005_lookup_result_carries_mode_time_currency_and_validity(session, delivery):
    result = call(
        session,
        "check_price_and_availability",
        {"product_ids": ["464306"], "delivery_date": delivery},
    )
    assert result["mode"] == "fixture"  # authored fixture terms, never presented as live
    evidence = result["products"]["464306"]
    assert evidence["mode"] == "fixture" and evidence["observed_at"] and evidence["expires_at"]
    assert evidence["currency"] == "EUR" and evidence["net"] and evidence["gross"]
    assert evidence["source"]["price"] and evidence["source"]["availability"]
    # What the model actually sees (guardrails.project) still carries mode, time and currency.
    seen = project("check_price_and_availability", result)["products"]["464306"]
    assert {"mode", "observed_at", "expires_at", "currency", "net", "gross"} <= seen.keys()


def test_tct005_lookup_quantity_and_price_state_their_unit(session, delivery):
    result = call(
        session,
        "check_price_and_availability",
        {"product_ids": ["464306"], "delivery_date": delivery},
    )
    for view in (result, project("check_price_and_availability", result)):
        evidence = view["products"]["464306"]
        assert evidence["available_sales_quantity"] is not None
        assert any("unit" in key for key in evidence), sorted(evidence)


def line_request(delivery, product_id="464306", amount="10", unit="L"):
    return {
        "request_id": "tct-" + str(uuid4())[:8],
        "destination": "hotel-helsinki",
        "delivery_date": delivery,
        "lines": [{"product_id": product_id, "amount": amount, "unit": unit}],
    }


@pytest.fixture
def prepared(session, delivery):
    call(session, "get_product", {"product_id": "464306"})
    call(
        session,
        "publish_meal_plan",
        {
            "title": "Milk",
            "portions": 1,
            "ingredients": [{"name": "milk", "amount": "10", "unit": "L", "product_id": "464306"}],
        },
    )
    return call(session, "prepare_order", line_request(delivery))


def test_tct005_publish_meal_plan_echoes_every_amount_with_its_unit(prepared, session):
    plan = session.plan.model_dump(mode="json")
    assert plan["ingredients"] and all(i["amount"] and i["unit"] for i in plan["ingredients"])


def test_tct005_prepare_order_lines_carry_quantity_unit_basis_and_evidence(prepared):
    snapshot = prepared["snapshot"]
    assert snapshot["currency"] == "EUR" and snapshot["mode"] == "fixture"
    assert snapshot["observed_at"] and snapshot["charges_basis"]
    assert snapshot["lines"]
    for line in snapshot["lines"]:
        assert_quantity_has_unit_and_basis(line["quantity"])
        assert_product_evidence_and_units(line["product_evidence"])
        commercial = line["commercial_evidence"]
        assert commercial["mode"] == "fixture" and commercial["observed_at"]
        assert commercial["currency"] == "EUR" and commercial["source"]["price"]


def test_tct005_proposal_view_given_to_the_model_keeps_units_basis_mode_and_time(prepared, session):
    again = call(session, "get_proposal", {"proposal_id": prepared["proposal_id"]})
    for output in (prepared, again):
        view = project("prepare_order", output)
        assert view["snapshot"]["mode"] == "fixture" and view["snapshot"]["observed_at"]
        assert view["snapshot"]["currency"] == "EUR" and view["snapshot"]["lines"]
        for line in view["snapshot"]["lines"]:
            assert_quantity_has_unit_and_basis(line["quantity"])
        assert view["request"]["lines"][0]["unit"] == "L"


def test_tct005_get_order_receipt_names_currency_and_evidence_mode(
    session, actor, prepared, confirm_terms
):
    receipt = ToolSession(actor, session.service)  # a later turn reading the saved receipt
    from aimo.service import Service

    confirm_terms(prepared)  # every agent role needs a recorded customer confirmation (WS-D)
    order = Service(session.service.connector).commit_order(
        actor,
        CommitRequest(
            proposal_id=prepared["proposal_id"], revision=1, idempotency_key=str(uuid4())
        ),
    )
    result = call(receipt, "get_order", {"order_id": order["order_id"]})
    assert result["currency"] == "EUR" and result["gross_total"] and result["evidence_mode"]
    assert result["status"] == "accepted_mock" and result["upstream_order_placed"] is False
    view = project("get_order", result)
    assert view["currency"] == "EUR" and view["evidence_mode"] == "fixture"


def test_tct005_recipe_tool_results_carry_units_basis_and_attribution(actor, service, recipe_data):
    session = ToolSession(actor, service)
    found = call(session, "search_recipes", {"query": "carbonara"})
    assert found["note"] and found["rerank_status"]
    recipe = found["recipes"][0]
    reference = {"recipe_id": recipe["recipe_id"], "version": recipe["version"]}
    detail = call(session, "get_recipe", reference)
    assert detail["version"] and detail["source"] and detail["attribution"] and detail["license"]
    assert all(i["unit"] and i["quantity"] for i in detail["recipe"]["ingredients"])

    plan = call(session, "scale_recipe", reference | {"portions": 200})["meal_plan"]
    assert plan["recipe_version"] and plan["attribution"] and plan["base_servings"]
    assert plan["ingredients"] and all(i["unit"] and i["amount"] for i in plan["ingredients"])
    assert {i["status"] for i in plan["ingredients"]} == {"unresolved"}
    assert all(i["reason"] for i in plan["ingredients"])  # unresolved says why, no invented unit

    for item in plan["ingredients"]:
        call(session, "get_product", {"product_id": "recipe-" + item["ingredient_id"]})
        plan = call(
            session,
            "match_ingredient",
            MatchIngredient(
                plan_id=plan["recipe_plan_id"],
                revision=plan["recipe_plan_revision"],
                ingredient_id=item["ingredient_id"],
                product_id="recipe-" + item["ingredient_id"],
            ).model_dump(mode="json"),
        )["meal_plan"]
    for item in plan["ingredients"]:
        assert item["status"] == "matched" and item["unit"] and item["amount"]
        assert item["purchase_unit"] and item["purchase_amount"]
        assert re.fullmatch(r"[a-f0-9]{64}", item["product_fingerprint"])
        assert_quantity_has_unit_and_basis(item["conversion"])
    reloaded = call(session, "get_recipe_plan", {"plan_id": plan["recipe_plan_id"]})["meal_plan"]
    assert reloaded == plan


def test_tct005_every_registered_tool_is_covered_by_a_result_check_here():
    """Fails when a tool is added: extend the TCT-005 checks above, then this list."""
    covered = {
        "search_products": "test_tct005_search_products_results_carry_evidence_and_units",
        "get_product": "test_tct005_get_product_result_carries_evidence_and_units",
        "get_purchase_policy": "no product or quantity (a currency limit; see the audit)",
        "search_memory": "no calculated quantity; compact memory results tested in test_memory.py",
        "manage_memory": "no calculated quantity; persistence and replay tested in test_memory.py",
        "check_price_and_availability": "test_tct005_lookup_result_carries_mode_time_currency",
        "publish_meal_plan": "test_tct005_publish_meal_plan_echoes_every_amount_with_its_unit",
        "prepare_order": "test_tct005_prepare_order_lines_carry_quantity_unit_basis_and_evidence",
        "get_proposal": "test_tct005_proposal_view_given_to_the_model_keeps_units_basis_mode",
        "get_order": "test_tct005_get_order_receipt_names_currency_and_evidence_mode",
        "list_substitution_candidates": "candidates carry the product facts and a checks block; "
        "test_the_agent_can_list_substitution_candidates_after_reading_the_product",
        "search_recipes": "test_tct005_recipe_tool_results_carry_units_basis_and_attribution",
        "get_recipe": "test_tct005_recipe_tool_results_carry_units_basis_and_attribution",
        "scale_recipe": "test_tct005_recipe_tool_results_carry_units_basis_and_attribution",
        "get_recipe_plan": "test_tct005_recipe_tool_results_carry_units_basis_and_attribution",
        "match_ingredient": "test_tct005_recipe_tool_results_carry_units_basis_and_attribution",
        "match_ingredients": "same plan result as match_ingredient; test_batch_match_tool_matches_every_ingredient_in_one_revision",
    }
    assert set(covered) == set(ALL_TOOLS), set(covered) ^ set(ALL_TOOLS)
