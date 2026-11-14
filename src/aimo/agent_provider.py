"""Bounded OpenAI-compatible function calling, independent of purchasing logic."""

import json
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from aimo.db import Problem

MAX_RESPONSE_BYTES = 1_000_000
MAX_CONTEXT_BYTES = 512_000


class FunctionCall(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    arguments: str = Field(max_length=64_000)


class ToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    type: Literal["function"]
    function: FunctionCall


class AssistantReply(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None = Field(default=None, max_length=20_000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def unique_call_ids(self):
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate tool call IDs")
        return self

    def message(self):
        result = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [call.model_dump() for call in self.tool_calls]
        return result


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


def check_deadline(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Problem(
            "LLM_TIMEOUT", "The assistant reached its time limit. Retry this message.", 504
        )
    return remaining


class ChatProvider:
    """One request plus at most one transient retry within the caller's deadline.

    The caller owns the HTTP client. Provider bodies are never included in errors.
    """

    def __init__(self, config, client):
        self.config, self.client = config, client
        if not config.llm_api_key:
            raise Problem(
                "LLM_NOT_CONFIGURED", "Set the server's LLM_API_KEY to enable the assistant.", 503
            )
        try:
            base = urlsplit(config.llm_base_url)
            valid = (
                base.scheme in ("http", "https")
                and bool(base.hostname)
                and not (base.username or base.password or base.query or base.fragment)
                and bool(config.llm_model.strip())
            )
            _ = base.port  # Reject malformed ports before making a request.
        except ValueError:
            valid = False
        if not valid:
            raise Problem(
                "LLM_CONFIGURATION", "Check the server's LLM_BASE_URL and LLM_MODEL.", 503
            )
        self.url = config.llm_base_url.rstrip("/") + "/chat/completions"

    def complete(self, messages, tools, deadline):
        payload = {
            "model": self.config.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "max_completion_tokens": 4000,
        }
        if len(encode(payload).encode()) > MAX_CONTEXT_BYTES:
            raise Problem(
                "LLM_CONTEXT_LIMIT",
                "This conversation exceeds the assistant context limit. "
                "Start a new conversation with the requirements; saved purchases remain available.",
                422,
            )
        for attempt in range(2):
            remaining = check_deadline(deadline)
            try:
                with self.client.stream(
                    "POST",
                    self.url,
                    headers={"Authorization": "Bearer " + self.config.llm_api_key},
                    json=payload,
                    timeout=min(self.config.llm_timeout_seconds, remaining),
                ) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise Problem(
                            "LLM_CONFIGURATION",
                            "The provider rejected the server's LLM_API_KEY or permissions.",
                            503,
                        )
                    transient = status in (408, 429, 500, 502, 503, 504)
                    if transient and response.headers.get("Retry-After"):
                        raise Problem(
                            "LLM_RATE_LIMITED",
                            "The provider is busy. Retry this message later.",
                            503,
                        )
                    if transient and attempt == 0:
                        continue
                    if not response.is_success:
                        raise Problem(
                            "LLM_UNAVAILABLE",
                            "The provider could not complete this request. "
                            "Check LLM_MODEL/provider configuration or retry later.",
                            503,
                        )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        check_deadline(deadline)
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise Problem(
                                "LLM_RESPONSE_INVALID", "The provider response was too large.", 502
                            )
                        body.extend(chunk)
                    check_deadline(deadline)
                    return self.parse(body)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt == 0:
                    continue
                raise Problem(
                    "LLM_UNAVAILABLE", "The provider could not be reached. Retry this message.", 503
                ) from None
            except httpx.HTTPError:
                raise Problem(
                    "LLM_UNAVAILABLE",
                    "The provider transport failed. Check server configuration.",
                    503,
                ) from None
        raise AssertionError("Provider attempts exhausted without a result")

    @staticmethod
    def parse(body):
        try:
            choice = json.loads(body)["choices"][0]
            if choice.get("finish_reason") in ("length", "content_filter"):
                raise ValueError("Incomplete provider response")
            return AssistantReply.model_validate(choice["message"])
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError):
            raise Problem(
                "LLM_RESPONSE_INVALID",
                "The provider returned an invalid or incomplete response. Retry this message.",
                502,
            ) from None
