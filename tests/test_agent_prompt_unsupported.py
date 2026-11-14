"""JNP3-POL-009: the model is told to report requirements the catalog cannot verify.

`Requirements.unsupported` makes an unverifiable requirement block the basket
(`REQUIREMENT_UNSUPPORTED`, needs_resolution). That only works if the model fills it, so the
instruction must be in what the model is sent: the system prompt and the tool schema. This test
reads both; it does not need a model.
"""

from aimo.agent import system_prompt
from aimo.agent_tools import ToolSession


def tools():
    identity = {"id": "internal:x", "buyer_id": "demo-hotel", "role": "agent", "_turn_id": "t-1"}
    return {
        d["function"]["name"]: d["function"] for d in ToolSession(identity, object()).definitions
    }


def test_system_prompt_tells_the_model_to_put_unverifiable_requirements_in_unsupported():
    prompt = " ".join(system_prompt().split())
    assert "requirements.unsupported" in prompt
    at = prompt.index("requirements.unsupported")
    nearby = prompt[max(0, at - 400) : at + 500]
    assert "gluten-free" in nearby and "prepare_order" in nearby
    assert "never say the products meet it" in nearby.lower()


def test_prepare_order_tool_description_names_the_field():
    description = " ".join(tools()["prepare_order"]["description"].split())
    assert "requirements.unsupported" in description and "needs_resolution" in description


def test_prepare_order_schema_carries_the_field_with_its_bounds():
    schema = tools()["prepare_order"]["parameters"]
    field = schema["$defs"]["Requirements"]["properties"]["unsupported"]
    assert field["maxItems"] == 10 and field["items"]["maxLength"] == 80
    assert "cannot verify" in field["description"]
