"""Diagnostic correlation and privacy, without any live provider or database."""

import asyncio
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from aimo.db import Problem
from aimo.observability import (
    RequestLoggingMiddleware,
    configure_logging,
    event,
    failure,
    log_context,
    observe_async_errors,
    operation,
    result_metadata,
)


@pytest.fixture(scope="session", autouse=True)
def database():
    yield


@pytest.fixture(autouse=True)
def reset_buyers():
    yield


def records(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "aimo.operations"]


def test_nonserializable_diagnostics_never_stringify_private_objects(caplog):
    class PrivateObject:
        def __str__(self):
            pytest.fail("arbitrary objects must never be stringified")

    with caplog.at_level(logging.INFO):
        event("test.metadata", detail=PrivateObject(), metric=float("nan"))
    assert records(caplog)[-1]["detail"] == "<PrivateObject>"
    assert records(caplog)[-1]["metric"] == "<nonfinite>"


def test_external_exception_logs_do_not_reintroduce_private_messages(caplog):
    configure_logging()
    with caplog.at_level(logging.WARNING):
        try:
            raise RuntimeError("private-exception-value")
        except RuntimeError:
            logging.getLogger("uvicorn.error").exception("private-message-value")
        logging.getLogger("psycopg.pool").warning("connection failed: %s", "private-url-value")
    rows = [json.loads(r.message) for r in caplog.records]
    assert rows[0]["event"] == "server.exception" and rows[0]["error_type"] == "RuntimeError"
    assert rows[1]["event"] == "database.pool_warning"
    assert rows[0]["runtime_id"] == rows[1]["runtime_id"]
    assert rows[0]["process_id"] == rows[1]["process_id"]
    assert "private-" not in caplog.text


def test_successful_domain_blockers_are_summarized_without_result_text():
    summary = result_metadata(
        {
            "policy_outcome": "needs_resolution",
            "mode": "live",
            "proposal_id": "private-invalid-id",
            "products": [{"name": "private product"}],
            "ingredients": [{"status": "unresolved", "name": "private ingredient"}],
            "text": "private narrative",
        }
    )
    assert summary == {
        "policy_outcome": "needs_resolution",
        "mode": "live",
        "ingredient_count": 1,
        "unresolved_count": 1,
        "unmatched_count": 1,
        "result_count": 1,
    }


def test_concurrent_contexts_are_isolated_and_restored(caplog):
    async def task(turn):
        with log_context(turn_id=turn):
            await asyncio.sleep(0)
            event("test.inside")
        event("test.outside")

    async def run():
        await asyncio.gather(task("first"), task("second"))

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    rows = records(caplog)
    assert {r["turn_id"] for r in rows if r["event"] == "test.inside"} == {"first", "second"}
    assert all("turn_id" not in r for r in rows if r["event"] == "test.outside")


def test_error_keeps_original_exception_and_locations_without_private_content(caplog):
    private = "password=super-private customer message SQL parameter"

    @operation("test.failure")
    def fail():
        raise Problem("PRODUCT_NOT_VERIFIED", private, 422)

    with caplog.at_level(logging.INFO), log_context(turn_id="turn", tool="match_ingredient"):
        with pytest.raises(Problem, match=private):
            fail()
    row = records(caplog)[-1]
    assert row["event"] == "test.failure.failed"
    assert row["error_code"] == "PRODUCT_NOT_VERIFIED"
    assert row["tool"] == "match_ingredient" and row["turn_id"] == "turn"
    assert row["frames"][-1]["function"] == "fail"
    assert row["duration_ms"] >= 0
    assert private not in caplog.text
    assert "raise Problem" not in caplog.text


def test_http_logs_templates_and_correlates_stream_without_headers_or_query(caplog):
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/items/{item_id}")
    def item(item_id: str):
        # Sync FastAPI handlers run in a thread; request context must cross that boundary.
        event("test.handler")

        async def body():
            event("test.stream")
            yield item_id

        return StreamingResponse(body())

    @app.get("/health/live")
    def healthy():
        return {}

    with caplog.at_level(logging.INFO), TestClient(app) as client:
        response = client.get(
            "/items/private-path?secret=private-query",
            headers={
                "Authorization": "Bearer private-key",
                "Cookie": "private-cookie",
                "X-Request-ID": "untrusted-id",
            },
        )
        client.get("/health/live")
        client.get("/private-unmatched?secret=private-query")
    rows = records(caplog)
    request_id = response.headers["x-request-id"]
    assert request_id != "untrusted-id"
    assert {r["request_id"] for r in rows[:3]} == {request_id}
    assert rows[2]["route"] == "/items/{item_id}"
    assert rows[-1]["route"] == "<unmatched>" and rows[-1]["status"] == 404
    assert not any(r.get("route") == "/health/live" for r in rows)
    text = json.dumps(rows)
    assert all(
        secret not in text
        for secret in (
            "private-path",
            "private-query",
            "private-key",
            "private-cookie",
            "private-unmatched",
        )
    )


def test_unexpected_http_error_has_correlated_diagnostics(caplog):
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/broken")
    def broken():
        raise RuntimeError("private database URL")

    with caplog.at_level(logging.INFO), TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/broken").status_code == 500
    row = records(caplog)[-1]
    assert row["status"] == 500 and row["route"] == "/broken"
    assert row["error_type"] == "RuntimeError" and row["request_id"]
    assert "private database URL" not in json.dumps(row)


def test_nested_async_operations_have_parent_ids_and_keep_cancellation(caplog):
    @operation("test.child")
    async def child():
        event("test.child.inside")
        raise asyncio.CancelledError()

    @operation("test.parent")
    async def parent():
        await child()

    with caplog.at_level(logging.INFO), pytest.raises(asyncio.CancelledError):
        asyncio.run(parent())
    rows = records(caplog)
    parent_start, child_start = rows[:2]
    assert child_start["parent_operation_id"] == parent_start["operation_id"]
    assert rows[-2]["event"] == "test.child.cancelled"
    assert rows[-1]["event"] == "test.parent.cancelled"
    assert len({r["runtime_id"] for r in rows}) == 1
    assert all(r["process_id"] > 0 for r in rows)


def test_logging_failure_never_changes_return_or_original_exception(monkeypatch):
    from aimo import observability

    original = Problem("TEST_FAILURE", "private-original")

    @operation("test.observer")
    def call(fail=False):
        if fail:
            raise original
        return {"result": "private-success"}

    monkeypatch.setattr(
        observability.log,
        "log",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("logger failed")),
    )
    assert call() == {"result": "private-success"}
    with pytest.raises(Problem) as caught:
        call(True)
    assert caught.value is original


def test_grouped_and_translated_validation_errors_keep_safe_root_cause():
    from pydantic import BaseModel, ConfigDict, ValidationError

    class Shape(BaseModel):
        model_config = ConfigDict(extra="forbid")
        quantity: int

    try:
        try:
            Shape.model_validate({"quantity": "private-value", "private-field": "private-extra"})
        except ValidationError:
            raise Problem("TOOL_RESULT_INVALID", "private-message") from None
    except Problem as exc:
        summary = failure(ExceptionGroup("private-group", [exc, ValueError("private-other")]))
    child = summary["exceptions"][0]
    assert child["error_code"] == "TOOL_RESULT_INVALID"
    assert child["cause"]["error_type"] == "ValidationError"
    assert child["cause"]["validation_error_count"] == 2
    assert child["cause"]["invalid_fields"] == ["<unknown>"]
    assert "private-" not in json.dumps(summary)


def test_sensitive_keys_are_redacted_and_metadata_is_bounded(caplog):
    with caplog.at_level(logging.INFO):
        event(
            "test.defense",
            token="private-token",
            payload={"text": "private-text"},
            nested={"api-key": "private-key", "ok": "x" * 2000},
        )
    row = records(caplog)[-1]
    assert row["token"] == row["payload"] == "<redacted>"
    assert row["nested"]["api-key"] == "<redacted>"
    assert len(row["nested"]["ok"]) < 1100
    assert "private-" not in json.dumps(row)


def test_unhandled_process_thread_and_async_hooks_hide_messages(monkeypatch, caplog):
    import sys
    import threading
    from types import SimpleNamespace

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    configure_logging()
    exc = RuntimeError("private-error")
    loop = asyncio.new_event_loop()
    previous = loop.get_exception_handler()
    try:
        with caplog.at_level(logging.INFO):
            sys.excepthook(RuntimeError, exc, None)
            threading.excepthook(SimpleNamespace(exc_type=RuntimeError, exc_value=exc))
            with observe_async_errors(loop):
                loop.call_exception_handler(
                    {"message": "private-loop", "exception": exc, "future": "private-future"}
                )
            assert loop.get_exception_handler() is previous
    finally:
        loop.close()
    assert [r["event"] for r in records(caplog)] == [
        "process.unhandled",
        "thread.unhandled",
        "async.unhandled",
    ]
    assert "private-" not in caplog.text


def test_validation_and_500_request_ids_are_logged_without_input(caplog):
    from pydantic import BaseModel, ConfigDict

    from aimo.errors import install

    class Body(BaseModel):
        model_config = ConfigDict(extra="forbid")
        quantity: int

    app = FastAPI()
    install(app)
    app.add_middleware(RequestLoggingMiddleware)

    @app.post("/validate")
    def validate(body: Body):
        return {}

    @app.get("/broken")
    def broken():
        raise RuntimeError("private-database-url")

    with caplog.at_level(logging.INFO), TestClient(app, raise_server_exceptions=False) as client:
        assert (
            client.post(
                "/validate", json={"quantity": "private-input", "private-field": "private-extra"}
            ).status_code
            == 422
        )
        response = client.get("/broken")
    rows = records(caplog)
    validation = next(r for r in rows if r["event"] == "http.validation_failed")
    assert validation["validation_error_count"] == 2
    assert response.headers["x-request-id"] == rows[-1]["request_id"]
    assert rows[-1]["outcome"] == "error" and not rows[-1]["response_complete"]
    assert "private-" not in json.dumps(rows)


def test_stream_failure_after_headers_is_not_logged_as_success(caplog):
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/stream")
    def stream():
        async def body():
            yield "first chunk"
            raise RuntimeError("private-stream-error")

        return StreamingResponse(body())

    with caplog.at_level(logging.INFO), TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/stream").status_code == 200
    row = records(caplog)[-1]
    assert row["status"] == 200 and row["response_started"]
    assert row["outcome"] == "error" and not row["response_complete"]
    assert row["response_chunks"] == 1
    assert "private-stream-error" not in json.dumps(row)


def test_http_cancellation_and_disconnect_are_observed_without_swallowing(caplog):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()
        raise asyncio.CancelledError()

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    scope = {"type": "http", "method": "GET", "path": "/private-path"}
    with caplog.at_level(logging.INFO), pytest.raises(asyncio.CancelledError):
        asyncio.run(RequestLoggingMiddleware(app)(scope, receive, send))
    row = records(caplog)[-1]
    assert row["outcome"] == "cancelled" and row["disconnected"]
    assert not row["response_complete"]
    assert "private-path" not in json.dumps(row)


def test_schema_probe_failure_is_private_and_remains_best_effort(monkeypatch, caplog):
    from contextlib import contextmanager

    from aimo import schema_state

    @contextmanager
    def broken():
        raise RuntimeError("private-postgres-url")
        yield

    monkeypatch.setattr(schema_state, "connection", broken)
    with caplog.at_level(logging.INFO):
        assert schema_state.missing_migrations() == []
    assert records(caplog)[-1]["event"] == "database.schema_probe_failed"
    assert "private-postgres-url" not in caplog.text


def test_metadata_serialization_failure_does_not_change_success(caplog):
    from pydantic import BaseModel, field_serializer

    class Shape(BaseModel):
        value: str

        @field_serializer("value")
        def serialize(self, value):
            raise ValueError("private-serializer")

    value = Shape(value="private-value")

    @operation("test.serialization")
    def call():
        return value

    with caplog.at_level(logging.INFO):
        assert call() is value
    assert any(r["event"] == "diagnostic.summary_failed" for r in records(caplog))
    assert records(caplog)[-1]["event"] == "test.serialization.completed"
    assert "private-" not in caplog.text


def test_api_startup_and_worker_readiness_failures_are_structured(monkeypatch, caplog):
    from aimo import upstream, worker
    from aimo.api import create_app

    def broken():
        raise RuntimeError("private-startup-credential")

    monkeypatch.setattr(upstream, "check_supplier_startup", broken)
    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError):
            with TestClient(create_app()):
                pass
        with pytest.raises(RuntimeError):
            worker.check_readiness()
    rows = records(caplog)
    assert any(r["event"] == "api.startup_failed" for r in rows)
    assert any(r["event"] == "worker.readiness.failed" for r in rows)
    assert not any(r["event"] == "api.started" for r in rows)
    assert "private-startup-credential" not in caplog.text


def test_result_summary_keeps_outer_proposal_id_with_optional_plan():
    from uuid import uuid4

    from aimo.chat_schemas import AgentTurn

    pid = str(uuid4())
    assert result_metadata(AgentTurn(text="private-answer", proposal_id=pid)) == {
        "proposal_id": pid
    }
