"""Chat transport selection and typed replies, independent of purchasing logic."""

import json
import logging
import time
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from aimo.agent_limits import MAX_OTHER_CALLS_PER_REPLY, MAX_TOOL_CALLS_PER_REPLY, PARALLEL_READS
from aimo.db import Problem
from aimo.observability import elapsed, event, failure, operation

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
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=MAX_TOOL_CALLS_PER_REPLY)
    # Opaque provider reasoning/signatures must survive the next tool round unchanged.
    # Never persisted to conversation history, rendered to customers or logged.
    reasoning_details: list[dict] | None = Field(default=None, repr=False)
    google_parts: list[dict] | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_calls(self):
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise PydanticCustomError("duplicate_call_ids", "Duplicate tool call IDs")
        if sum(c.function.name not in PARALLEL_READS for c in self.tool_calls) > MAX_OTHER_CALLS_PER_REPLY:
            raise PydanticCustomError("other_call_limit", "Too many non-read calls")
        return self

    def message(self):
        result = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [call.model_dump() for call in self.tool_calls]
        if self.reasoning_details is not None:
            result["reasoning_details"] = self.reasoning_details
        if self.google_parts is not None:
            result["google_parts"] = self.google_parts
        return result


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


def response_rejected(exc, category):
    """Log fixed categories only: validation inputs/messages may contain secrets."""
    if isinstance(exc, ValidationError):
        kinds = {e["type"] for e in exc.errors(include_input=False, include_context=False)}
        category = next(
            (k for k in ("duplicate_call_ids", "other_call_limit", "too_long") if k in kinds),
            "schema",
        )
    event("llm.response_rejected", level=logging.WARNING, validation_category=category)


def check_deadline(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Problem(
            "LLM_TIMEOUT", "The assistant reached its time limit. Retry this message.", 504
        )
    return remaining


def chat_provider(config, client):
    """Select a transport explicitly; never fall back when a provider fails."""
    if getattr(config, "llm_provider", "openrouter") == "google":
        from aimo.google_chat import GoogleChatProvider

        return GoogleChatProvider(config, client)
    return ChatProvider(config, client)


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
            host = base.hostname
            try:
                loopback = host == "localhost" or ip_address(host).is_loopback
            except ValueError:
                loopback = False
            valid = (
                (base.scheme == "https" or (base.scheme == "http" and loopback))
                and bool(host)
                and not (base.username or base.password or base.query or base.fragment)
                and bool(config.llm_model.strip())
            )
            _ = base.port  # Reject malformed ports before making a request.
        except ValueError:
            valid = False
        if not valid:
            raise Problem(
                "LLM_CONFIGURATION",
                "Use an HTTPS LLM_BASE_URL (HTTP is allowed only for loopback development) "
                "and a valid LLM_MODEL.",
                503,
            )
        self.url = config.llm_base_url.rstrip("/") + "/chat/completions"

    @operation("llm.completion")
    def complete(self, messages, tools, deadline):
        from aimo.attachments import image_context_bytes, openai_messages

        payload = {
            "model": self.config.llm_model,
            "messages": openai_messages(messages),
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "max_completion_tokens": getattr(self.config, "llm_max_completion_tokens", 8192),
        }
        effort = getattr(self.config, "llm_reasoning_effort", "")
        if effort:
            payload["reasoning_effort"] = effort
        image_bytes = image_context_bytes(messages)
        if len(encode(payload).encode()) - image_bytes > MAX_CONTEXT_BYTES or image_bytes > 6_000_000:
            raise Problem(
                "LLM_CONTEXT_LIMIT",
                "This conversation exceeds the assistant context limit. "
                "Start a new conversation with the requirements; saved purchases remain available.",
                422,
            )
        for attempt in range(2):
            remaining = check_deadline(deadline)
            started = time.monotonic()
            try:
                with self.client.stream(
                    "POST",
                    self.url,
                    headers={"Authorization": "Bearer " + self.config.llm_api_key},
                    json=payload,
                    timeout=min(self.config.llm_timeout_seconds, remaining),
                ) as response:
                    status = response.status_code
                    event(
                        "llm.response",
                        model=self.config.llm_model,
                        attempt=attempt + 1,
                        status=status,
                        duration_ms=elapsed(started),
                    )
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
                        event(
                            "llm.retry", level=logging.WARNING, attempt=attempt + 1, status=status
                        )
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
                    # Record bounded metadata even when parsing rejects a truncated reply.
                    try:
                        data = json.loads(body)
                    except ValueError:
                        data = {}
                    data = data if isinstance(data, dict) else {}
                    usage = data.get("usage")
                    usage = usage if isinstance(usage, dict) else {}
                    choices = data.get("choices")
                    choice = choices[0] if isinstance(choices, list) and choices else {}
                    choice = choice if isinstance(choice, dict) else {}
                    finish_reason = choice.get("finish_reason")
                    message = choice.get("message")
                    calls = message.get("tool_calls") if isinstance(message, dict) else None
                    event(
                        "llm.result",
                        model=self.config.llm_model,
                        finish_reason=finish_reason
                        if finish_reason
                        in ("stop", "length", "tool_calls", "content_filter", "error", None)
                        else "other",
                        tool_call_count=len(calls) if isinstance(calls, list) else None,
                        duration_ms=elapsed(started),
                        usage={
                            k: usage[k]
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                            if type(usage.get(k)) is int
                        },
                    )
                    reply_data = choice.get("message")
                    reply_calls = reply_data.get("tool_calls") if isinstance(reply_data, dict) else None
                    event("llm.response_shape", response_bytes=len(body),
                          candidate_count=len(choices) if isinstance(choices, list) else 0,
                          tool_call_count=len(reply_calls) if isinstance(reply_calls, list) else None)
                    return self.parse(body)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                event(
                    "llm.transport_failed",
                    level=logging.WARNING,
                    attempt=attempt + 1,
                    duration_ms=elapsed(started),
                    **failure(exc),
                )
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
        category = "shape"
        try:
            choice = json.loads(body)["choices"][0]
            if choice.get("finish_reason") in ("length", "content_filter"):
                category = "incomplete"
                raise ValueError("Incomplete provider response")
            return AssistantReply.model_validate(choice["message"])
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError) as exc:
            response_rejected(exc, category)
            raise Problem(
                "LLM_RESPONSE_INVALID",
                "The provider returned an invalid or incomplete response. Retry this message.",
                502,
            ) from None
