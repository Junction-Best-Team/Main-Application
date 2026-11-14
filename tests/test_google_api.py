"""Authored HTTP fixtures; no Google calls, billing, or database work."""

import json

import httpx
import pytest

from aimo.google_api import GoogleAPIError, google_api_request


@pytest.fixture(autouse=True)
def database():
    """The portable client has no database dependency."""


@pytest.fixture(autouse=True)
def reset_buyers():
    """Override the global purchasing fixture for these transport-only tests."""


@pytest.mark.parametrize(
    ("operation", "model", "payload", "path", "expected_body"),
    [
        (
            "generate_content",
            "models/gemini-4-carbon",
            {"contents": [{"role": "user", "parts": [{"text": "Plan lunch"}]}]},
            "/v1beta/models/gemini-4-carbon:generateContent",
            {"contents": [{"role": "user", "parts": [{"text": "Plan lunch"}]}]},
        ),
        (
            "embed_content",
            "gemini-embedding-2",
            {"content": {"parts": [{"text": "pasta"}]}, "outputDimensionality": 768},
            "/v1beta/models/gemini-embedding-2:embedContent",
            {"content": {"parts": [{"text": "pasta"}]}, "outputDimensionality": 768},
        ),
        (
            "decide",
            "gemini-decision-1",
            {"input": "pasta", "questions": {"food": {"type": "noul"}}},
            "/v1beta/decisions",
            {
                "model": "gemini-decision-1",
                "input": "pasta",
                "questions": {"food": {"type": "noul"}},
            },
        ),
    ],
)
def test_native_requests_and_lossless_responses(operation, model, payload, path, expected_body):
    # Keep opaque provider metadata intact for replay across tool rounds. Images
    # use the same generateContent endpoint; base64 data must also survive.
    response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "thoughtSignature": "opaque",
                            "functionCall": {"name": "search", "args": {}},
                        },
                        {"inlineData": {"mimeType": "image/png", "data": "authored-base64"}},
                    ]
                }
            }
        ]
    }

    def handler(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path == path
        assert not request.url.query
        assert request.method == "POST"
        assert request.headers["x-goog-api-key"] == "private-test-key"
        assert "authorization" not in request.headers
        assert json.loads(request.content) == expected_body
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert (
            google_api_request(
                operation, model=model, payload=payload, api_key="private-test-key", client=client
            )
            == response
        )
        assert not client.is_closed
    assert "model" not in payload


def test_discovery_pagination_and_environment_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "environment-test-key")

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/v1beta/models"
        assert dict(request.url.params) == {"pageSize": "10", "pageToken": "next"}
        assert request.headers["x-goog-api-key"] == "environment-test-key"
        assert not request.content
        return httpx.Response(200, json={"models": [], "nextPageToken": "later"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = google_api_request(
            "list_models", payload={"pageSize": 10, "pageToken": "next"}, client=client
        )
    assert result["nextPageToken"] == "later"


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
def test_errors_hide_provider_body_and_never_redirect_or_retry(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://example.com/stolen", "Retry-After": "1"},
            json={"error": {"message": "private-test-key and sensitive prompt"}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(GoogleAPIError) as caught:
            google_api_request("list_models", api_key="private-test-key", client=client)
    assert len(requests) == 1
    assert caught.value.status_code == status
    assert "private-test-key" not in str(caught.value)
    assert "sensitive prompt" not in str(caught.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_failures_are_safe_and_not_retried(error):
    calls = []

    def handler(request):
        calls.append(request)
        raise error("sensitive transport details", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GoogleAPIError) as caught:
            google_api_request("list_models", api_key="test-key", client=client)
    assert len(calls) == 1
    assert "sensitive" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("content", [b"not json", b"[]", b'{"error":"secret"}'])
def test_invalid_responses(content):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    ) as client:
        with pytest.raises(GoogleAPIError, match="INVALID_RESPONSE"):
            google_api_request("list_models", api_key="test-key", client=client)


def test_response_size_is_bounded():
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 101))
    ) as client:
        with pytest.raises(GoogleAPIError, match="RESPONSE_TOO_LARGE"):
            google_api_request(
                "list_models", api_key="test-key", client=client, max_response_bytes=100
            )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "https://example.com/key"},
        {"model": "../other"},
        {"model": "gemini?key=secret"},
        {"model": "gemini", "payload": {"model": "other"}},
        {"model": "gemini", "timeout": float("inf")},
    ],
)
def test_invalid_configuration_sends_nothing(kwargs):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("invalid configuration reached network")
        )
    ) as client:
        with pytest.raises(ValueError):
            google_api_request("generate_content", api_key="test-key", client=client, **kwargs)


def test_explicit_empty_key_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "environment-test-key")
    with pytest.raises(GoogleAPIError, match="KEY_MISSING_OR_INVALID"):
        google_api_request("list_models", api_key="")
