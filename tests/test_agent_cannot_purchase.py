"""Owner decision Q-14: the agent can never purchase. Its tool registry has no operation that
confirms, approves or commits, and no agent module calls the Service/workflow functions that do.
"""

import ast
from pathlib import Path

import pytest

from aimo.agent_tools import ToolSession
from aimo.db import Problem

SRC = Path(__file__).resolve().parents[1] / "src" / "aimo"
READ_AND_PREPARE = {
    "search_products",
    "get_product",
    "get_purchase_policy",
    "check_price_and_availability",
    "prepare_order",
    "get_proposal",
    "get_order",
}
# Recipe discovery and deterministic scaling (PR #38, always registered since PR #103): no purchasing.
RECIPE_TOOLS = {
    "search_recipes",
    "get_recipe",
    "scale_recipe",
    "get_recipe_plan",
    "match_ingredient",
    "match_ingredients",
}
MEMORY_TOOLS = {"search_memory", "manage_memory"}
MEMORY_SERVICE = MEMORY_TOOLS | {"memory_context", "get_memory", "replay_memory"}
PURCHASING = {
    "commit_order",
    "record_human_decision",
    "confirm",
    "authorize_commit",
    "approval_detail",
    "list_approvals",
    "set_product_scope",
    "update_purchase_policy",
    "withdraw_meal_authorization",
}


class Recorder:
    """Stands in for Service; any call it did not expect is recorded."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"unexpected Service call {name}")

        return record


def session():
    identity = {"id": "internal:x", "buyer_id": "demo-hotel", "role": "agent", "_turn_id": "t-1"}
    return ToolSession(identity, Recorder())


def test_registry_exposes_only_read_and_prepare_operations():
    names = set(session().registry)
    extra = RECIPE_TOOLS
    assert names - {"publish_meal_plan"} == READ_AND_PREPARE | extra | MEMORY_TOOLS
    assert not [
        n for n in names if any(word in n for word in ("confirm", "approve", "commit", "decide"))
    ]
    advertised = {d["function"]["name"] for d in session().definitions}
    assert advertised == names


@pytest.mark.parametrize(
    "name",
    [
        "approve",
        "confirm",
        "confirm_purchase",
        "commit_order",
        "record_human_decision",
        "decide",
        "set_product_scope",
        "update_purchase_policy",
        "withdraw_meal_authorization",
    ],
)
def test_purchasing_operations_cannot_be_invoked_by_name(name):
    tools = session()
    with pytest.raises(Problem) as error:
        tools.invoke(name, "{}")
    assert (error.value.code, error.value.status) == ("TOOL_NOT_ALLOWED", 422)
    assert tools.service.calls == []


def test_registry_handlers_call_only_read_and_prepare_service_methods():
    """Every Service method reachable from agent_tools.py is on the allowed list."""
    tree = ast.parse((SRC / "agent_tools.py").read_text())
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "service"
    }
    assert used, "expected the tool handlers to call self.service"
    assert used <= READ_AND_PREPARE | RECIPE_TOOLS | MEMORY_SERVICE, (
        used - READ_AND_PREPARE - RECIPE_TOOLS - MEMORY_SERVICE
    )


@pytest.mark.parametrize("module", ["agent.py", "agent_tools.py", "agent_provider.py"])
def test_agent_modules_never_reference_purchasing_functions(module):
    tree = ast.parse((SRC / module).read_text())
    referenced = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.ImportFrom):
            referenced |= {a.name for a in node.names}
    assert referenced & PURCHASING == set(), referenced & PURCHASING
