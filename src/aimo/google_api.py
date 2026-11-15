"""Portable Google Gemini REST helper. Requires only httpx and the standard library.

Native responses (including function-call thought signatures and image bytes) are
returned unchanged. Application provider selection belongs to its adapters.
"""

import json
import math
import os
import re
from contextlib import ExitStack
from typing import Any, Callable, Literal

import httpx

GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GoogleOperation = Literal[
    "generate_content", "embed_content", "decide", "list_models", "create_live_token"
]


class GoogleAPIError(RuntimeError):
    """Safe to display: never includes provider bodies, prompts, or credentials."""

    def __init__(self, code: str, status_code: int | None = None):
        self.code = code
        self.status_code = status_code
        super().__init__(f"Google API: {code}" + (f" (HTTP {status_code})" if status_code else ""))


def google_api_request(
    operation: GoogleOperation,
    *,
    model: str | None = None,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30,
    max_response_bytes: int = 32 * 1024 * 1024,
    observer: Callable[[str, dict], None] | None = None,
) -> dict[str, Any]:
    """Call Google's API for generation, embeddings, decisions, discovery, or Live tokens.

    ``payload`` uses Google's native JSON fields; for ``list_models`` it contains
    query parameters such as pageSize/pageToken. Pass an explicit key or export
    GEMINI_API_KEY. This standalone module never reads .env or imports app config.
    Live token payloads use the native REST ``bidiGenerateContentSetup`` field;
    streaming audio itself uses the Live WebSocket endpoint, not this helper.

    A supplied client stays open and can reuse its connection pool. Redirects are
    disabled even for supplied clients, so credentials stay on Google's host.
    There are no automatic retries: a timed-out generation may already be billed.
    Timeout is an HTTPX per-operation timeout, not an overall application deadline.
    An optional observer receives only transport metadata, never content or headers.
    """
    def observe(stage, **fields):
        if observer:
            try:
                observer(stage, fields)
            except Exception:
                pass  # Observability cannot repeat paid requests or change their result.

    if operation not in (
        "generate_content", "embed_content", "decide", "list_models", "create_live_token"
    ):
        raise ValueError("Unsupported Google API operation")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if max_response_bytes <= 0:
        raise ValueError("max_response_bytes must be positive")
    key = (api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
    if not key or any(char.isspace() for char in key):
        raise GoogleAPIError("KEY_MISSING_OR_INVALID")
    body = dict(payload) if payload is not None else {}
    if operation == "list_models":
        if model is not None:
            raise ValueError("list_models does not accept a model")
        if set(body) - {"pageSize", "pageToken"}:
            raise ValueError("list_models accepts only pageSize and pageToken")
        method, path = "GET", "/models"
        content = None
    elif operation == "create_live_token":
        if model is not None:
            raise ValueError("Constrain the Live model inside payload.bidiGenerateContentSetup")
        method, path = "POST", "/auth_tokens"
        content = json.dumps(body, allow_nan=False).encode("utf-8")
    else:
        name = model.removeprefix("models/") if model else ""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", name):
            raise ValueError("Use a Google model ID, optionally prefixed with models/")
        if "model" in body:
            raise ValueError("Pass model as an argument, not inside payload")
        if operation == "decide":
            path = "/decisions"
            body["model"] = name
        else:
            action = "generateContent" if operation == "generate_content" else "embedContent"
            path = f"/models/{name}:{action}"
        method = "POST"
        content = json.dumps(body, allow_nan=False).encode("utf-8")

    observe("request", request_bytes=len(content) if content else 0,
            timeout_seconds=timeout, max_response_bytes=max_response_bytes)
    with ExitStack() as stack:
        active_client = client if client is not None else stack.enter_context(httpx.Client())
        try:
            with active_client.stream(
                method,
                GOOGLE_API_BASE + path,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                content=content,
                params=body if method == "GET" else None,
                timeout=timeout,
                follow_redirects=False,
            ) as response:
                observe("response", status=response.status_code)
                if not response.is_success:
                    code = (
                        "AUTH_REJECTED"
                        if response.status_code in (401, 403)
                        else "RATE_LIMITED"
                        if response.status_code == 429
                        else "REQUEST_FAILED"
                    )
                    raise GoogleAPIError(code, response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > max_response_bytes:
                        observe("body_limit", response_bytes=len(data), incoming_bytes=len(chunk))
                        raise GoogleAPIError("RESPONSE_TOO_LARGE")
                    data.extend(chunk)
        except httpx.TimeoutException as exc:
            phase = next((name for kind, name in (
                (httpx.ConnectTimeout, "connect"), (httpx.ReadTimeout, "read"),
                (httpx.WriteTimeout, "write"), (httpx.PoolTimeout, "pool"),
            ) if isinstance(exc, kind)), "unknown")
            observe("transport_failed", transport_type="timeout", timeout_phase=phase)
            raise GoogleAPIError("TIMEOUT") from None
        except httpx.HTTPError:
            observe("transport_failed", transport_type="http")
            raise GoogleAPIError("TRANSPORT_ERROR") from None
    observe("body", response_bytes=len(data))
    try:
        result = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise GoogleAPIError("INVALID_RESPONSE") from None
    if not isinstance(result, dict) or "error" in result:
        raise GoogleAPIError("INVALID_RESPONSE")
    return result
