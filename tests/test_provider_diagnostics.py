"""Authored transport failures and shape diagnostics; no paid API calls."""

import json
import logging

import httpx
import pytest

from aimo.google_api import GoogleAPIError
from aimo.google_api import google_api_request as portable_request
from aimo.google_provider import google_api_request
from aimo.observability import log_context


@pytest.fixture(scope="session", autouse=True)
def database():
    yield


@pytest.fixture(autouse=True)
def reset_buyers():
    yield


def records(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "aimo.operations"]


def test_native_metadata_is_correlated_and_contains_no_content(caplog):
    result = {
        "candidates": [
            {
                "finishReason": "MAX_TOKENS",
                "content": {
                    "parts": [
                        {
                            "thought": True,
                            "text": "private-reasoning",
                            "thoughtSignature": "private-signature",
                        },
                        {
                            "functionCall": {
                                "name": "private-tool",
                                "args": {"password": "private-arg"},
                            }
                        },
                        {"inlineData": {"data": "private-image"}},
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": 8,
            "private-field": "private-usage",
        },
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result))
    ) as client:
        with (
            caplog.at_level(logging.INFO),
            log_context(turn_id="turn", attempt_id="attempt", boundary="request_brief"),
        ):
            actual = google_api_request(
                "generate_content",
                model="gemini-test",
                api_key="private-key",
                client=client,
                payload={"contents": [{"text": "private-request"}]},
                timeout=12,
            )
    assert actual == result
    rows = records(caplog)
    assert len({r["operation_id"] for r in rows}) == 1
    assert all(r["turn_id"] == "turn" and r["boundary"] == "request_brief" for r in rows)
    shape = next(r for r in rows if r["event"] == "provider.google.result")
    assert shape["finish_reasons"] == ["MAX_TOKENS"]
    assert (
        shape["tool_call_count"] == shape["thought_part_count"] == shape["inline_part_count"] == 1
    )
    assert shape["usage"] == {
        "promptTokenCount": 100,
        "candidatesTokenCount": 20,
        "thoughtsTokenCount": 8,
    }
    assert next(r for r in rows if r["event"] == "provider.google.request")["timeout_seconds"] == 12
    assert next(r for r in rows if r["event"] == "provider.google.body")["response_bytes"] > 0
    assert "private-" not in json.dumps(rows)


@pytest.mark.parametrize(
    "status,body,code",
    [
        (401, b"private-body", "AUTH_REJECTED"),
        (429, b"private-body", "RATE_LIMITED"),
        (500, b"private-body", "REQUEST_FAILED"),
        (200, b"private-not-json", "INVALID_RESPONSE"),
        (200, b'{"error":{"message":"private-error"}}', "INVALID_RESPONSE"),
    ],
)
def test_translated_provider_failures_keep_status_and_safe_cause(caplog, status, body, code):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, content=body))
    ) as client:
        with caplog.at_level(logging.INFO), pytest.raises(GoogleAPIError) as caught:
            google_api_request(
                "embed_content", model="gemini-test", api_key="private-key", client=client
            )
    assert caught.value.code == code
    rows = records(caplog)
    assert next(r for r in rows if r["event"] == "provider.google.response")["status"] == status
    failed = rows[-1]
    assert failed["event"] == "provider.google.failed" and failed["provider_error"] == code
    assert "private-" not in json.dumps(rows)


@pytest.mark.parametrize(
    "error,phase",
    [
        (httpx.ConnectTimeout, "connect"),
        (httpx.ReadTimeout, "read"),
        (httpx.WriteTimeout, "write"),
        (httpx.PoolTimeout, "pool"),
    ],
)
def test_timeout_phase_survives_error_translation_without_retry(caplog, error, phase):
    attempts = []

    def handler(request):
        attempts.append(request)
        raise error("private-url")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level(logging.INFO), pytest.raises(GoogleAPIError) as caught:
            google_api_request(
                "decide", model="gemini-decision-1", api_key="private-key", client=client
            )
    assert caught.value.code == "TIMEOUT" and len(attempts) == 1
    rows = records(caplog)
    assert (
        next(r for r in rows if r["event"] == "provider.google.transport_failed")["timeout_phase"]
        == phase
    )
    assert rows[-1]["cause"]["error_type"] == error.__name__
    assert "private-" not in json.dumps(rows)


def test_body_limit_and_unknown_finish_reason_are_safe(caplog):
    body = {
        "candidates": [{"finishReason": "private-finish", "content": {"parts": []}}],
        "promptFeedback": {"blockReason": "private-block"},
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        with caplog.at_level(logging.INFO):
            google_api_request(
                "generate_content", model="gemini-test", api_key="private-key", client=client
            )
            with pytest.raises(GoogleAPIError, match="RESPONSE_TOO_LARGE"):
                google_api_request(
                    "generate_content",
                    model="gemini-test",
                    api_key="private-key",
                    client=client,
                    max_response_bytes=8,
                )
    rows = records(caplog)
    shape = next(r for r in rows if r["event"] == "provider.google.result")
    assert shape["finish_reasons"] == ["other"] and shape["block_reason"] == "other"
    assert any(r["event"] == "provider.google.body_limit" for r in rows)
    assert "private-" not in json.dumps(rows)


def test_portable_observer_failure_does_not_change_transport_or_result():
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(200, json={"name": "private-ephemeral-token"})

    def broken(*args):
        raise RuntimeError("observer failed")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = portable_request(
            "create_live_token", api_key="private-key", client=client, observer=broken
        )
    assert result == {"name": "private-ephemeral-token"} and len(attempts) == 1
