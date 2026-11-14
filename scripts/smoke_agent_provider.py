"""Two live-provider completions with an authored read-only policy tool result.

No database, supplier, purchasing mutation or secrets in output. Missing provider
configuration prints `skipped`; use --require-config in an operator acceptance run.
"""

import argparse
import json
import time

import httpx

from aimo.agent_provider import ChatProvider
from aimo.agent_tools import EmptyRequest
from aimo.config import settings
from aimo.db import Problem


def smoke(config):
    tool = {
        "type": "function",
        "function": {
            "name": "get_purchase_policy",
            "description": "Read a fixture policy; cannot buy.",
            "parameters": EmptyRequest.model_json_schema(),
        },
    }
    history = [
        {
            "role": "system",
            "content": "This is a read-only function-calling smoke test. "
            "Call get_purchase_policy with an empty object exactly once, then briefly explain "
            "that the customer must confirm a purchase. Do not invent tool results.",
        },
        {"role": "user", "content": "Read the policy and explain who can confirm."},
    ]
    deadline = time.monotonic() + 60
    with httpx.Client(follow_redirects=False) as client:
        provider = ChatProvider(config, client)
        first = provider.complete(history, [tool], deadline)
        if len(first.tool_calls) != 1 or first.tool_calls[0].function.name != "get_purchase_policy":
            raise Problem(
                "SMOKE_FAILED", "The provider did not request the expected read-only tool."
            )
        EmptyRequest.model_validate_json(first.tool_calls[0].function.arguments)
        history.append(first.message())
        history.append(
            {
                "role": "tool",
                "tool_call_id": first.tool_calls[0].id,
                "content": json.dumps(
                    {
                        "mode": "authored_fixture",
                        "purchase_authorized": False,
                        "confirmation": "authenticated customer action",
                    }
                ),
            }
        )
        final = provider.complete(history, [tool], deadline)
        if final.tool_calls or not final.content or not final.content.strip():
            raise Problem("SMOKE_FAILED", "The provider did not complete the tool round trip.")
    return {
        "status": "passed",
        "provider": "live",
        "tool_result": "authored_fixture",
        "completions": 2,
        "purchase_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-config", action="store_true")
    args = parser.parse_args()
    cfg = settings()
    if not cfg.llm_api_key:
        print(json.dumps({"status": "skipped", "reason": "LLM_API_KEY is not configured"}))
        return 1 if args.require_config else 0
    try:
        result = smoke(cfg)
    except Problem as exc:
        print(json.dumps({"status": "failed", "code": exc.code}))
        return 1
    except ValueError:
        print(json.dumps({"status": "failed", "code": "SMOKE_INVALID_TOOL_ARGUMENTS"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
