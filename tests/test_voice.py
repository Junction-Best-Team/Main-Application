"""Voice authorization/token contracts, with authored Google responses only."""

import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aimo import voice
from aimo.api import create_app
from aimo.config import settings
from aimo.db import connection
from aimo.google_api import GoogleAPIError


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


@pytest.fixture
def headers(http):
    response = http.post("/api/login", headers={"Origin": "http://testserver"}, json={
        "username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"],
    })
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def conversation(http, headers):
    response = http.post("/api/conversations", headers=headers, json={
        "title": "Voice test", "idempotency_key": str(uuid4()),
    })
    assert response.status_code == 200
    return response.json()["id"]


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-authored-google-key")
    monkeypatch.setenv("VOICE_ENABLED", "true")
    settings.cache_clear()
    calls = []

    def request(operation, **kwargs):
        calls.append((operation, kwargs))
        return {"name": "auth_tokens/short-lived-authored-token"}

    monkeypatch.setattr(voice, "google_api_request", request)
    yield calls
    settings.cache_clear()


def test_voice_requires_session_origin_csrf_and_owned_conversation(http, headers, conversation, google):
    url = f"/api/conversations/{conversation}/voice-session"
    assert http.post(url).status_code == 403
    assert http.post(url, headers=headers | {"Origin": "https://evil.invalid"}).status_code == 403
    assert http.post(url, headers=headers | {"X-CSRF-Token": "wrong"}).status_code == 403
    assert http.post(f"/api/conversations/{uuid4()}/voice-session", headers=headers).status_code == 404
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other-voice','999',1)")
        c.execute("UPDATE conversations SET buyer_id='other-voice' WHERE id=%s", (conversation,))
    assert http.post(url, headers=headers).status_code == 404
    http.cookies.clear()
    assert http.post(url, headers=headers).status_code == 401
    assert google == []


def test_voice_uses_shared_helper_with_fully_locked_single_use_setup(http, headers, conversation, google):
    response = http.post(f"/api/conversations/{conversation}/voice-session", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["token"] == "auth_tokens/short-lived-authored-token"
    assert "private-authored-google-key" not in response.text
    operation, kwargs = google[0]
    assert operation == "create_live_token"
    assert kwargs["api_key"] == "private-authored-google-key"
    payload = kwargs["payload"]
    assert payload["uses"] == 1
    assert "fieldMask" not in payload  # Entire setup locked, including absent fields.
    setup = payload["bidiGenerateContentSetup"]
    assert setup == body["setup"]
    assert setup["model"] == "models/gemini-3.8-live"
    declarations = setup["tools"][0]["functionDeclarations"]
    assert [tool["name"] for tool in declarations] == ["ask_aimo"]
    assert "verbatim" in setup["systemInstruction"]["parts"][0]["text"]
    assert datetime.fromisoformat(payload["expireTime"]) - datetime.fromisoformat(payload["newSessionExpireTime"]) == timedelta(minutes=4)
    detail = http.get(f"/api/conversations/{conversation}").json()
    assert not detail["messages"] and not detail["purchases"]


def test_voice_minting_is_rate_limited_before_provider_call(http, headers, conversation, google):
    url = f"/api/conversations/{conversation}/voice-session"
    for _ in range(5):
        assert http.post(url, headers=headers).status_code == 200
    response = http.post(url, headers=headers)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "300"
    assert len(google) == 5


@pytest.mark.parametrize("enabled,key", [("false", "key"), ("true", "")])
def test_unconfigured_voice_keeps_text_chat_available(http, headers, conversation, monkeypatch, enabled, key):
    monkeypatch.setenv("VOICE_ENABLED", enabled)
    monkeypatch.setenv("GEMINI_API_KEY", key)
    settings.cache_clear()
    try:
        response = http.post(f"/api/conversations/{conversation}/voice-session", headers=headers)
        assert response.status_code == 503
        assert http.get(f"/api/conversations/{conversation}").status_code == 200
    finally:
        settings.cache_clear()


def test_voice_failures_hide_provider_secrets(http, headers, conversation, google, monkeypatch):
    def fail(*args, **kwargs):
        raise GoogleAPIError("AUTH_REJECTED", 403)
    monkeypatch.setattr(voice, "google_api_request", fail)
    response = http.post(f"/api/conversations/{conversation}/voice-session", headers=headers)
    assert response.status_code == 503
    assert "private" not in response.text and "AUTH_REJECTED" not in response.text


def test_voice_refuses_unfinished_chat(http, headers, conversation, google):
    response = http.post(f"/api/conversations/{conversation}/messages", headers=headers, json={
        "text": "Plan lunch", "idempotency_key": str(uuid4()),
    })
    assert response.status_code == 200
    assert http.post(f"/api/conversations/{conversation}/voice-session", headers=headers).status_code == 409
    assert google == []
