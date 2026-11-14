"""Content-free diagnostic events. Never pass payloads, URLs or exception messages here."""

import json
import logging
import math
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from uuid import UUID, uuid4

_context = ContextVar("aimo_log_context", default={})
log = logging.getLogger("aimo.operations")


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("aimo").setLevel(logging.INFO)
    # HTTPX logs full URLs; API access events below use matched route templates instead.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in ("uvicorn.error", "psycopg.pool"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, SafeExternalErrors) for f in logger.filters):
            logger.addFilter(SafeExternalErrors())


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
        started, status, error = time.monotonic(), 500, None

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = message | {
                    "headers": list(message.get("headers", []))
                    + [
                        (b"x-request-id", request_id.encode("ascii")),
                    ]
                }
            await send(message)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, receive, observed_send)
            except Exception as exc:
                error = failure(exc)
                raise
            finally:
                route = getattr(scope.get("route"), "path", "<unmatched>")
                # Health probes are noisy; failures still get an event.
                if status >= 400 or error or route not in ("/health/live", "/health/ready"):
                    event(
                        "http.request",
                        level=logging.WARNING if status >= 400 or error else logging.INFO,
                        route=route,
                        method=scope["method"]
                        if scope["method"]
                        in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
                        else "OTHER",
                        status=status,
                        duration_ms=elapsed(started),
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
    log.log(
        level,
        json.dumps(
            safe_metadata(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": name,
                    "level": logging.getLevelName(level),
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
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else "<nonfinite>"
    if depth >= 6:
        return "<depth-limit>"
    if isinstance(value, dict):
        return {
            k if type(k) is str else "<unknown>": safe_metadata(v, depth + 1)
            for k, v in list(value.items())[:80]
        }
    if isinstance(value, (list, tuple)):
        return [safe_metadata(v, depth + 1) for v in value[:80]]
    return "<" + type(value).__name__ + ">"


def failure(exc):
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
    return result


def elapsed(start):
    return round((time.monotonic() - start) * 1000, 2)


def result_metadata(result):
    """Summarize domain outcomes that return successfully but can still block a basket."""
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
    }.items():
        if isinstance(result.get(key), str) and result[key] in allowed:
            summary[key] = result[key]
    plan = result.get("meal_plan", result)
    if isinstance(plan, dict):
        for key in ("proposal_id", "recipe_plan_id"):
            try:
                if isinstance(plan.get(key), (str, UUID)):
                    summary[key] = str(UUID(str(plan[key])))
            except (KeyError, ValueError, TypeError, AttributeError):
                pass
        for key in ("revision", "recipe_plan_revision"):
            if type(plan.get(key)) is int:
                summary[key] = plan[key]
        ingredients = plan.get("ingredients")
        if isinstance(ingredients, list):
            summary["ingredient_count"] = len(ingredients)
            summary["unresolved_count"] = sum(
                isinstance(i, dict) and i.get("status") == "unresolved" for i in ingredients
            )
    for key in ("products", "recipes", "items"):
        if isinstance(result.get(key), list):
            summary["result_count"] = len(result[key])
            break
    return summary


def operation(name, *, context_arg=None):
    """Observe a sync boundary without changing its return, exceptions or retry behavior."""

    def decorate(fn):
        @wraps(fn)
        def observed(*args, **kwargs):
            context = {}
            if context_arg:
                value = args[0] if args else kwargs[context_arg]
                if context_arg == "turn":
                    context = {
                        "turn_id": str(value["id"]),
                        "conversation_id": str(value["conversation_id"]),
                        "attempt_id": str(value["attempt"]),
                    }
                else:
                    context = {
                        k: str(value[v])
                        for k, v in {
                            "turn_id": "_turn_id",
                            "conversation_id": "_conversation_id",
                            "attempt_id": "_attempt",
                        }.items()
                        if value.get(v) is not None
                    }
            with log_context(**context):
                start = time.monotonic()
                event(name + ".started")
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    event(
                        name + ".failed",
                        level=logging.WARNING,
                        duration_ms=elapsed(start),
                        **failure(exc),
                    )
                    raise
                event(name + ".completed", duration_ms=elapsed(start), **result_metadata(result))
                return result

        return observed

    return decorate
