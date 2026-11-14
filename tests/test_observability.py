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
    log_context,
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
