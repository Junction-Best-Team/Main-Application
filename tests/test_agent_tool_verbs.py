"""JNP3-TCT-007, gaps left by test_agent_cannot_purchase.py (read that file first).

That file proves the registry NAMES, the `self.service.<method>` calls in agent_tools.py and the
absence of purchasing identifiers in agent*.py. It does not prove: what the model is actually
SENT (parameter names of the provider-facing schema), that no ToolSession method reaches the
Service outside a registered handler, that every Service/workflow operation is refused by name
(including ones added later), that name variants and extra arguments cannot smuggle a verb in,
or that a real prepare_order leaves orders, confirmations, policies and approvals untouched.
"""

import ast
import inspect
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from wsc_support import counts

from aimo import approval_workflow
from aimo.agent_tools import ToolSession
from aimo.db import Problem, connection
from aimo.service import Service

SRC = Path(__file__).resolve().parents[1] / "src" / "aimo"
VERBS = ("approve", "confirm", "commit", "decide", "decision", "authorize", "policy_edit")
# Field names a model must never be able to set: identity, authority and retry keys are
# server-side; rules/limits/scope are policy content.
FORBIDDEN_FIELDS = {
    "approve",
    "approved",
    "confirm",
    "confirmed",
    "commit",
    "decision",
    "decide",
    "actor_id",
    "approver",
    "buyer_id",
    "agent_id",
    "identity",
    "identity_id",
    "session",
    "csrf_token",
    "idempotency_key",
    "rules",
    "policy",
    "policy_version",
    "autonomous_limit",
    "max_gross",
    "exceptions",
    "authority",
    "scope",
    "approved_products",
}
# Service methods the tool handlers are allowed to reach (read and prepare only).
ALLOWED_SERVICE = {
    "search_products",
    "get_product",
    "get_purchase_policy",
    "check_price_and_availability",
    "prepare_order",
    "get_proposal",
    "get_order",
    "list_substitution_candidates",
    "ensure_saved_plan_resolved",
    "search_recipes",
    "get_recipe",
    "scale_recipe",
    "get_recipe_plan",
    "match_ingredient",
    "match_ingredients",
    "search_memory",
    "manage_memory",
    "memory_context",
    "get_memory",
    "replay_memory",
}


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"unexpected Service call {name}")

        return record


def session(service=None):
    identity = {"id": "internal:x", "buyer_id": "demo-hotel", "role": "agent", "_turn_id": "t-1"}
    return ToolSession(identity, service or Recorder())


def property_names(schema):
    """Every property name anywhere in a JSON schema, including $defs and nested objects."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                found.update(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


# ---- what the model is actually sent -----------------------------------------------------


def test_provider_facing_schemas_expose_no_decision_identity_or_policy_field():
    definitions = session().definitions
    assert definitions
    leaked = {
        d["function"]["name"]: property_names(d["function"]["parameters"])
        & (
            FORBIDDEN_FIELDS
            - ({"scope"} if d["function"]["name"] in {"search_memory", "manage_memory"} else set())
        )
        for d in definitions
    }
    assert {name: fields for name, fields in leaked.items() if fields} == {}


def test_provider_facing_tool_names_contain_no_decision_verb():
    names = [d["function"]["name"] for d in session().definitions]
    assert [n for n in names if any(v in n for v in VERBS)] == []


def test_descriptions_that_mention_authority_only_deny_it():
    for definition in session().definitions:
        text = definition["function"]["description"].lower()
        for word in ("approve", "confirm", "commit", "authorize"):
            if word in text:
                assert "not" in text or "no " in text, definition["function"]["name"]
    prepare = next(d for d in session().definitions if d["function"]["name"] == "prepare_order")
    assert "Does not authorize or commit a purchase" in prepare["function"]["description"]


def test_every_request_model_forbids_extra_fields():
    for name, spec in session().registry.items():
        assert spec.request.model_config.get("extra") == "forbid", name


def test_the_runner_sends_session_definitions_and_the_provider_has_no_tool_list_of_its_own():
    """The schema list the model sees is session.definitions, passed through unchanged."""
    runner = ast.parse((SRC / "agent.py").read_text())
    completes = [
        ast.unparse(n)
        for n in ast.walk(runner)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "provider.complete"
    ]
    assert completes == ["provider.complete(history, session.definitions, deadline)"]
    provider_source = (SRC / "agent_provider.py").read_text()
    provider = ast.parse(provider_source)
    assert '"tools": tools' in provider_source
    literals = [
        n.value
        for n in ast.walk(provider)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    # No hard-coded tool name or function-schema literal lives in the provider module.
    assert [s for s in literals if s in set(session().registry) | {"commit_order", "confirm"}] == []
    assert "ToolSpec" not in provider_source and "registry" not in provider_source


# ---- no hidden path from a ToolSession to the Service ------------------------------------


def test_only_registered_handlers_reach_the_service():
    """Any ToolSession method that calls self.service.* is a registered handler (or __init__
    for the two recipe lambdas), so there is no unregistered route to Service."""
    tree = ast.parse((SRC / "agent_tools.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ToolSession")
    users = {}
    for method in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
        used = {
            c.func.attr
            for c in ast.walk(method)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and isinstance(c.func.value, ast.Attribute)
            and c.func.value.attr == "service"
        }
        if used:
            users[method.name] = used
    handlers = {spec.handler.__name__ for spec in session().registry.values()}
    # Since PR #103 the recipe tools are always registered: no method reaches the Service
    # without being a registered handler.
    unregistered = set(users) - {"__init__", "memory_context"} - handlers
    assert unregistered == set(), unregistered
    assert set().union(*users.values()) <= ALLOWED_SERVICE


def test_invoke_resolves_names_only_through_the_registry():
    source = inspect.getsource(ToolSession.invoke)
    assert "self.registry.get(name)" in source
    assert "getattr" not in source and "eval" not in source


# ---- every other operation is refused by name --------------------------------------------


def public_callables(obj):
    return {
        n
        for n, v in inspect.getmembers(obj, callable)
        if not n.startswith("_") and (inspect.isfunction(v) or inspect.ismethod(v))
    }


def test_every_other_service_and_workflow_operation_is_refused_by_name():
    """Derived from the code, so a Service method added later is covered automatically."""
    other_service = public_callables(Service) - ALLOWED_SERVICE
    workflow = {
        n
        for n, v in vars(approval_workflow).items()
        if inspect.isfunction(v)
        and not n.startswith("_")
        and v.__module__ == approval_workflow.__name__
    }
    candidates = other_service | workflow
    assert "commit_order" in other_service
    assert "commit_order" in candidates
    tools = session()
    refused = {}
    for name in sorted(candidates - set(tools.registry)):
        with pytest.raises(Problem) as error:
            tools.invoke(name, "{}")
        refused[name] = (error.value.code, error.value.status)
    assert set(refused.values()) == {("TOOL_NOT_ALLOWED", 422)}
    assert tools.service.calls == []


@pytest.mark.parametrize(
    "name",
    [
        "Commit_Order",
        "COMMIT_ORDER",
        " commit_order",
        "commit_order ",
        "commit_order\n",
        "commit_order\x00",
        "functions.commit_order",
        "tools.commit_order",
        "prepare_order.commit",
        "prepare_order/commit",
        "prepare_order;commit_order",
        "confirm_purchase",
        "edit_policy",
        "set_policy",
        "update_policy",
        "approve_proposal",
        "approve_order",
        "decide_approval",
        "",
        "__init__",
        "registry",
        "service",
    ],
)
def test_name_variants_cannot_reach_a_purchasing_operation(name):
    tools = session()
    with pytest.raises(Problem) as error:
        tools.invoke(name, "{}")
    assert (error.value.code, error.value.status) == ("TOOL_NOT_ALLOWED", 422)
    assert tools.service.calls == []


def test_non_string_tool_names_are_refused():
    tools = session()
    for name in (None, 0, ["commit_order"], {"name": "commit_order"}):
        with pytest.raises((Problem, TypeError)):
            tools.invoke(name, "{}")
    assert tools.service.calls == []


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("search_products", {"query": "milk"}),
        ("get_product", {"product_id": "464306"}),
        ("get_purchase_policy", {}),
        (
            "check_price_and_availability",
            {"product_ids": ["464306"], "delivery_date": "2026-12-01"},
        ),
        ("get_proposal", {"proposal_id": "00000000-0000-0000-0000-000000000001"}),
        ("get_order", {"order_id": "00000000-0000-0000-0000-000000000001"}),
    ],
)
@pytest.mark.parametrize(
    "extra",
    [
        {"commit": True},
        {"confirm": True},
        {"approve": True},
        {"decision": "approve"},
        {"policy": {"rules": {}}},
        {"actor_id": "buyer"},
        {"buyer_id": "other"},
    ],
    ids=lambda e: next(iter(e)),
)
def test_a_smuggled_decision_argument_is_rejected_before_any_service_call(tool, arguments, extra):
    tools = session()
    with pytest.raises(Problem) as error:
        tools.invoke(tool, json.dumps(arguments | extra))
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"
    assert tools.service.calls == []


# ---- behaviour against the real Service --------------------------------------------------


def test_a_real_prepare_order_creates_a_proposal_but_no_order_confirmation_or_policy_change(
    agent, service
):
    """The agent identity here has real autonomous authority (demo-agent); prepare still
    only saves a proposal. Orders and customer confirmations stay at zero."""
    identity = dict(agent) | {"_turn_id": "t-surface"}
    tools = ToolSession(identity, service)
    delivery = (date.today() + timedelta(days=2)).isoformat()
    tools.invoke("get_product", json.dumps({"product_id": "464306"}))
    tools.invoke(
        "publish_meal_plan",
        json.dumps(
            {
                "title": "Milk",
                "portions": 1,
                "ingredients": [
                    {"name": "milk", "amount": "10", "unit": "L", "product_id": "464306"}
                ],
            }
        ),
    )
    with connection() as c:
        policy_before = c.execute(
            "SELECT current_policy FROM buyers WHERE id=%s", (identity["buyer_id"],)
        ).fetchone()["current_policy"]
        rules_before = c.execute(
            "SELECT buyer_id,version,rules FROM policies ORDER BY 1,2"
        ).fetchall()
    before = counts()
    proposal = tools.invoke(
        "prepare_order",
        json.dumps(
            {
                "request_id": "surface-check",
                "destination": "hotel-helsinki",
                "delivery_date": delivery,
                "lines": [{"product_id": "464306", "amount": "10", "unit": "L"}],
            }
        ),
    )
    after = counts()
    assert proposal["proposal_id"]
    assert not proposal.get("order_id")
    assert after["proposals"] == before["proposals"] + 1
    for table in ("orders", "customer_confirmations", "idempotency", "policies"):
        assert after[table] == before[table], table
    with connection() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM approvals WHERE status='approved'").fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT current_policy FROM buyers WHERE id=%s", (identity["buyer_id"],)
            ).fetchone()["current_policy"]
            == policy_before
        )
        assert (
            c.execute("SELECT buyer_id,version,rules FROM policies ORDER BY 1,2").fetchall()
            == rules_before
        )
        assert not c.execute(
            "SELECT 1 FROM audit_events WHERE event ILIKE ANY(%s)",
            (["%confirm%", "%commit%", "%approved%", "%policy%"],),
        ).fetchone()
