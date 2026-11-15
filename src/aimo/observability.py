"""Content-free diagnostic events. Never pass payloads, URLs or exception messages here."""

import asyncio
import inspect
import json
import logging
import math
import os
import sys
import threading
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from uuid import UUID, uuid4

_context = ContextVar("aimo_log_context", default={})
log = logging.getLogger("aimo.operations")
_runtime = {"runtime_id": str(uuid4()), "process_id": os.getpid()}
_PRIVATE_FIELDS = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "api_key",
        "headers",
        "payload",
        "body",
        "messages",
        "contents",
        "arguments",
        "prompt",
        "sql",
        "parameters",
        "image_data",
        "audio",
        "transcript",
        "response_text",
        "exception_message",
        "x_api_key",
        "access_token",
        "refresh_token",
        "database_url",
        "dsn",
        "cloudinary_url",
        "client_secret",
        "idempotency_key",
    }
)


def configure_logging(component=None):
    if _runtime["process_id"] != os.getpid():
        _runtime.update(process_id=os.getpid(), runtime_id=str(uuid4()))
    if component:
        _runtime["component"] = component
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("aimo").setLevel(logging.INFO)
    # HTTPX logs full URLs; API access events below use matched route templates instead.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in ("uvicorn.error", "psycopg.pool"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, SafeExternalErrors) for f in logger.filters):
            logger.addFilter(SafeExternalErrors())
    # The defaults print arbitrary exception text, including connection URLs.
    sys.excepthook = _process_exception
    threading.excepthook = _thread_exception


def _process_exception(kind, exc, tb):
    if issubclass(kind, KeyboardInterrupt):
        return
    event("process.unhandled", level=logging.CRITICAL, **failure(exc))


def _thread_exception(args):
    if args.exc_type is not SystemExit:
        event("thread.unhandled", level=logging.ERROR, **failure(args.exc_value))


@contextmanager
def observe_async_errors(loop):
    """Catch detached-task failures without logging loop messages, tasks or futures."""
    previous = loop.get_exception_handler()

    def handler(loop, context):
        exc = context.get("exception")
        event(
            "async.unhandled",
            level=logging.ERROR,
            **failure(exc) if isinstance(exc, BaseException) else {},
        )

    loop.set_exception_handler(handler)
    try:
        yield
    finally:
        loop.set_exception_handler(previous)


class SafeExternalErrors(logging.Filter):
    """Uvicorn tracebacks and pool warnings can otherwise re-log private exception text."""

    def filter(self, record):
        if record.exc_info or (record.name == "psycopg.pool" and record.levelno >= logging.WARNING):
            details = failure(record.exc_info[1]) if record.exc_info and record.exc_info[1] else {}
            record.msg = json.dumps(
                safe_metadata(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event": "server.exception" if record.exc_info else "database.pool_warning",
                        "level": record.levelname,
                        **_runtime,
                        **_context.get(),
                        **details,
                    }
                )
            )
            record.args, record.exc_info, record.exc_text = (), None, None
        return True


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Generated here rather than trusting arbitrary client-provided header text.
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started, status, error = time.monotonic(), 500, None
        response_started, response_complete, disconnected = False, False, False
        response_bytes, chunks = 0, 0
        time_to_headers_ms = None
        outcome = "complete"

        async def observed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def observed_send(message):
            nonlocal \
                status, \
                response_started, \
                response_complete, \
                response_bytes, \
                chunks, \
                time_to_headers_ms
            if message["type"] == "http.response.start":
                status = message["status"]
                message = message | {
                    "headers": list(message.get("headers", []))
                    + [
                        (b"x-request-id", request_id.encode("ascii")),
                    ]
                }
            await send(message)
            if message["type"] == "http.response.start":
                response_started = True
                time_to_headers_ms = elapsed(started)
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
                chunks += 1
                response_complete = not message.get("more_body", False)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, observed_receive, observed_send)
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except Exception as exc:
                error = failure(exc)
                outcome = "error"
                raise
            finally:
                route = getattr(scope.get("route"), "path", "<unmatched>")
                if outcome == "complete" and not response_complete:
                    outcome = "disconnected" if disconnected else "incomplete"
                # Health probes are noisy; failures still get an event.
                if (
                    status >= 400
                    or error
                    or outcome != "complete"
                    or route not in ("/health/live", "/health/ready")
                ):
                    event(
                        "http.request",
                        level=logging.ERROR
                        if status >= 500 or error
                        else logging.WARNING
                        if status >= 400 or outcome != "complete"
                        else logging.INFO,
                        route=route,
                        method=scope["method"]
                        if scope["method"]
                        in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
                        else "OTHER",
                        status=status if response_started or error else None,
                        duration_ms=elapsed(started),
                        outcome=outcome,
                        response_started=response_started,
                        response_complete=response_complete,
                        disconnected=disconnected,
                        response_bytes=response_bytes,
                        response_chunks=chunks,
                        time_to_headers_ms=time_to_headers_ms,
                        **{k: v for k, v in (error or {}).items() if k != "status"},
                    )


@contextmanager
def log_context(**fields):
    token = _context.set(_context.get() | fields)
    try:
        yield
    finally:
        _context.reset(token)


def event(name, *, level=logging.INFO, **fields):
    # Diagnostics must never undo a purchase or replace the original exception.
    try:
        _event(name, level=level, **fields)
    except Exception:
        pass


def _event(name, *, level, **fields):
    log.log(
        level,
        json.dumps(
            safe_metadata(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": name,
                    "level": logging.getLevelName(level),
                    **_runtime,
                    **_context.get(),
                    **fields,
                }
            ),
            ensure_ascii=True,
            allow_nan=False,
        ),
    )


def safe_metadata(value, depth=0):
    """Diagnostics must not fail a request or stringify an arbitrary exception/object."""
    if type(value) is str:
        return value if len(value) <= 1024 else value[:1024] + "<truncated>"
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else "<nonfinite>"
    if depth >= 6:
        return "<depth-limit>"
    if isinstance(value, dict):
        return {
            k if type(k) is str else "<unknown>": "<redacted>"
            if type(k) is str and k.lower().replace("-", "_") in _PRIVATE_FIELDS
            else safe_metadata(v, depth + 1)
            for k, v in list(value.items())[:80]
        }
    if isinstance(value, (list, tuple)):
        return [safe_metadata(v, depth + 1) for v in value[:80]]
    return "<" + type(value).__name__ + ">"


def validation_metadata(exc, fields=()):
    """Keep schema-owned field names and error types; never loc keys, inputs or messages."""
    errors = exc.errors()
    return {
        "validation_error_count": len(errors),
        "error_types": dict(Counter(e["type"] for e in errors)),
        "invalid_fields": sorted(
            {e["loc"][0] if e.get("loc") and e["loc"][0] in fields else "<unknown>" for e in errors}
        ),
    }


def failure(exc, _depth=0):
    """Keep code locations, never traceback source lines, locals, SQL or exception text."""
    result = {
        "error_type": type(exc).__name__,
        "frames": [
            {
                "file": frame.filename.rsplit("/", 1)[-1],
                "function": frame.name,
                "line": frame.lineno,
            }
            for frame in traceback.extract_tb(exc.__traceback__)[-12:]
        ],
    }
    # Import lazily: db also uses diagnostics for pool failures.
    from aimo.db import Problem

    if isinstance(exc, Problem):
        result.update(error_code=exc.code, status=exc.status, retry_after=exc.retry_after)
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        result.update(validation_metadata(exc))
    # Only fixed internal enums are exposed; arbitrary .code/.category attributes are private.
    if type(exc).__module__ == "aimo.google_api" and type(exc).__name__ == "GoogleAPIError":
        allowed = {
            "AUTH_REJECTED",
            "RATE_LIMITED",
            "TIMEOUT",
            "REQUEST_FAILED",
            "TRANSPORT_ERROR",
            "RESPONSE_TOO_LARGE",
            "INVALID_RESPONSE",
            "KEY_MISSING_OR_INVALID",
        }
        result.update(
            provider_error=exc.code if exc.code in allowed else "other",
            provider_status=exc.status_code if type(exc.status_code) is int else None,
        )
    if type(exc).__module__ == "aimo.guardrails" and type(exc).__name__ == "GuardError":
        allowed = {
            "auth",
            "rate_limited",
            "timeout",
            "network",
            "transport",
            "unavailable",
            "malformed",
            "model_mismatch",
            "too_large",
            "deadline",
            "call_budget",
            "not_configured",
        }
        result["guardrail_error"] = exc.category if exc.category in allowed else "other"
    if _depth < 3:
        if isinstance(exc, BaseExceptionGroup):
            result["exception_count"] = len(exc.exceptions)
            result["exceptions"] = [failure(e, _depth + 1) for e in exc.exceptions[:4]]
        # Adapters deliberately hide raw messages with `from None`; safe root-cause
        # types/locations still explain what was lost during that translation.
        cause = exc.__cause__ or exc.__context__
        if cause is not None and cause is not exc:
            result["cause"] = failure(cause, _depth + 1)
    return result


def elapsed(start):
    return round((time.monotonic() - start) * 1000, 2)


def result_metadata(result):
    """Summarize domain outcomes that return successfully but can still block a basket."""
    from pydantic import BaseModel

    if isinstance(result, BaseModel):
        result = result.model_dump()
    if not isinstance(result, dict):
        return {}
    summary = {}
    for key, allowed in {
        "policy_outcome": {"ready_to_commit", "approval_required", "denied", "needs_resolution"},
        "approval_status": {
            "pending",
            "approved",
            "rejected",
            "expired",
            "not_required",
            "unconfirmed",
            "superseded",
            "authorization_withdrawn",
            "policy_changed",
            "authority_changed",
        },
        "order_status": {"not_placed", "accepted_mock"},
        "mode": {"live", "fixture"},
        "rerank_status": {"disabled", "applied", "unavailable"},
    }.items():
        if isinstance(result.get(key), str) and result[key] in allowed:
            summary[key] = result[key]
    plan = result.get("meal_plan", result)
    for source in (result, plan):
        if not isinstance(source, dict):
            continue
        for key in ("proposal_id", "recipe_plan_id"):
            try:
                if isinstance(source.get(key), (str, UUID)):
                    summary[key] = str(UUID(str(source[key])))
            except (KeyError, ValueError, TypeError, AttributeError):
                pass
        for key in ("revision", "recipe_plan_revision"):
            if type(source.get(key)) is int:
                summary[key] = source[key]
    if isinstance(plan, dict):
        ingredients = plan.get("ingredients")
        if isinstance(ingredients, list):
            summary["ingredient_count"] = len(ingredients)
            summary["unresolved_count"] = sum(
                isinstance(i, dict) and i.get("status") == "unresolved" for i in ingredients
            )
            summary["unmatched_count"] = sum(
                isinstance(i, dict)
                and (
                    not i.get("product_id")
                    or (bool(plan.get("recipe_plan_id")) and i.get("status") != "matched")
                )
                for i in ingredients
            )
    for key in ("products", "recipes", "items"):
        if isinstance(result.get(key), list):
            summary["result_count"] = len(result[key])
            break
    return summary


def _completion_metadata(result):
    try:
        return result_metadata(result)
    except Exception as exc:
        event("diagnostic.summary_failed", level=logging.WARNING, **failure(exc))
        return {}


def operation(name, *, context_arg=None, log_success=True):
    """Observe sync/async boundaries without changing results, errors or retries."""

    def decorate(fn):
        @contextmanager
        def observe(args, kwargs):
            context = {}
            if context_arg:
                value = args[0] if args else kwargs.get(context_arg)
                if isinstance(value, dict):
                    names = (
                        {
                            "turn_id": "id",
                            "conversation_id": "conversation_id",
                            "attempt_id": "attempt",
                        }
                        if context_arg == "turn"
                        else {
                            "turn_id": "_turn_id",
                            "conversation_id": "_conversation_id",
                            "attempt_id": "_attempt",
                        }
                    )
                    context = {
                        k: str(value[v])
                        for k, v in names.items()
                        if isinstance(value.get(v), (str, UUID))
                    }
            with log_context(
                **context,
                parent_operation_id=_context.get().get("operation_id"),
                operation_id=str(uuid4()),
            ):
                start = time.monotonic()
                if log_success:
                    event(name + ".started")
                metadata = {}
                try:
                    yield metadata
                except asyncio.CancelledError:
                    event(name + ".cancelled", level=logging.WARNING, duration_ms=elapsed(start))
                    raise
                except Exception as exc:
                    event(
                        name + ".failed",
                        level=logging.WARNING,
                        duration_ms=elapsed(start),
                        **failure(exc),
                    )
                    raise
                if log_success:
                    event(name + ".completed", duration_ms=elapsed(start), **metadata)

        @wraps(fn)
        def observed(*args, **kwargs):
            with observe(args, kwargs) as metadata:
                result = fn(*args, **kwargs)
                metadata.update(_completion_metadata(result))
                return result

        @wraps(fn)
        async def observed_async(*args, **kwargs):
            with observe(args, kwargs) as metadata:
                result = await fn(*args, **kwargs)
                metadata.update(_completion_metadata(result))
                return result

        return observed_async if inspect.iscoroutinefunction(fn) else observed

    return decorate
