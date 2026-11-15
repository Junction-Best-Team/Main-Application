"""Q-108: a chat turn that fails because the model provider fails stores one plain assistant notice.

The notice is a fixed, deterministic text (no model call) in the language of the customer's last
message (Finnish, English or Swedish, English when unsure), marked with `notice="provider_unavailable"`
so the UI shows it as a notice and the model's history skips it. The unfinished message keeps its
retry offer; a retry removes the notice and, once answered, leaves only the real reply. Fixture mode.
"""

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aimo import conversations
from aimo.api import create_app
from aimo.chat_schemas import AgentTurn, ConversationCreate, ConversationResponse, MessageRequest
from aimo.db import Problem, connection
from aimo.turn_notice import NOTICE_TEXT, TIMEOUT_TEXT, failure_notice, language_of
from aimo.worker import run_once

PROVIDER_CODES = [
    "LLM_TIMEOUT",
    "LLM_UNAVAILABLE",
    "LLM_RATE_LIMITED",
    "LLM_RESPONSE_INVALID",
    "LLM_NOT_CONFIGURED",
    "LLM_CONFIGURATION",
    "LLM_CONTEXT_LIMIT",
]
EN = "I could not reach the assistant just now. Please try again."


def failing(code="LLM_UNAVAILABLE", message="provider key sk-secret rejected at api.example.test"):
    def runner(actor, history, shared, **extra):
        raise Problem(code, message, 503)

    return runner


def answering(text="Here is your answer."):
    seen = []

    def runner(actor, history, shared, **extra):
        seen.append(history)
        return AgentTurn(text=text)

    runner.seen = seen
    return runner


@pytest.fixture
def conv(buyer):
    return conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]


def send(buyer, service, cid, runner, text="Find me lactose-free milk.", key=None):
    body = MessageRequest(text=text, idempotency_key=key or str(uuid4()))
    return body, conversations.message(buyer, cid, body, service, runner)


def stored(cid):
    with connection() as c:
        return c.execute(
            "SELECT * FROM conversation_messages WHERE conversation_id=%s ORDER BY id", (cid,)
        ).fetchall()


def notices(cid):
    return [m for m in stored(cid) if m["role"] == "assistant" and m["notice"]]


# --- language and text --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,language",
    [
        ("Find me lactose-free milk for the hotel breakfast.", "en"),
        ("Tarvitsen kerman ja maitoa viikonlopun tapahtumaan.", "fi"),
        ("Yritetään uudelleen, kiitos.", "fi"),
        ("Hej, kan du hjälpa mig att hitta ett recept för 100 portioner soppa?", "sv"),
        ("Jag behöver mjölk och grädde, tack.", "sv"),
        ("Haluan tilata maitoa hotellille.", "fi"),
        ("", "en"),
        ("1234 !!!", "en"),
        ("Bonjour, je voudrais du lait.", "en"),  # unknown language: English
        ("Place my order now. Kiitos.", "en"),  # one stray word is not enough
    ],
)
def test_the_language_follows_the_customers_last_message_with_an_english_fallback(text, language):
    assert language_of(text) == language
    assert failure_notice(text) == NOTICE_TEXT[language]


def test_the_three_texts_are_fixed_and_say_nothing_about_the_cause():
    assert NOTICE_TEXT["en"] == EN
    assert NOTICE_TEXT["fi"] == "En saanut yhteyttä avustajaan juuri nyt. Yritä uudelleen."
    assert NOTICE_TEXT["sv"] == "Jag kunde inte nå assistenten just nu. Försök igen."
    for text in NOTICE_TEXT.values():
        assert not any(word in text.lower() for word in ("llm", "provider", "model", "error", "key"))


# --- the stored notice --------------------------------------------------------------------------


@pytest.mark.parametrize("code", PROVIDER_CODES)
def test_a_provider_failure_stores_exactly_one_notice_and_keeps_the_retry(buyer, service, conv, code):
    body = MessageRequest(text="Find me milk.", idempotency_key=str(uuid4()))
    with pytest.raises(Problem) as raised:
        conversations.message(buyer, conv, body, service, failing(code))
    assert raised.value.code == code  # the worker still sees and logs the real error
    (notice,) = notices(conv)
    assert notice["text"] == (TIMEOUT_TEXT["en"] if code == "LLM_TIMEOUT" else EN)
    assert notice["notice"] == "provider_unavailable"
    assert notice["meal_plan"] is None and notice["proposal_id"] is None and notice["image"] is None
    view = conversations.detail(buyer, conv)
    assert view["retry_message"]["idempotency_key"] == body.idempotency_key
    assert [(m["role"], m["notice"]) for m in view["messages"]] == [
        ("user", None),
        ("assistant", "provider_unavailable"),
    ]
    with connection() as c:
        state = c.execute("SELECT state FROM conversation_turns").fetchone()["state"]
    assert state == "failed"


def test_no_raw_error_or_provider_detail_reaches_the_notice_or_the_view(buyer, service, conv):
    secret = "sk-secret-123 api.example.test openrouter gemini"
    with pytest.raises(Problem):
        send(buyer, service, conv, failing("LLM_UNAVAILABLE", secret))
    view = json.dumps(conversations.detail(buyer, conv), default=str)
    for leaked in ("sk-secret", "api.example.test", "openrouter", "gemini", "LLM_UNAVAILABLE"):
        assert leaked not in view


@pytest.mark.parametrize(
    "error",
    [
        Problem("PROVIDER_FAILED", "Retry this message", 503),
        Problem("GUARDRAIL_UNAVAILABLE", "The safety check is unavailable", 503),
        Problem("TURN_REPLACED", "replaced", 409),
        Problem("COMMIT_BLOCKED", "blocked", 409),
        ValueError("a bug is not a provider failure"),
    ],
    ids=lambda e: getattr(e, "code", type(e).__name__),
)
def test_other_failures_store_no_notice(buyer, service, conv, error):
    def runner(actor, history, shared, **extra):
        raise error

    with pytest.raises(type(error)):
        send(buyer, service, conv, runner)
    assert notices(conv) == []
    assert [m["role"] for m in stored(conv)] == ["user"]


def test_a_stale_worker_attempt_writes_no_notice(buyer, service, conv):
    """A reclaimed lease changes the attempt: the old attempt's failure must not write anything."""

    def runner(actor, history, shared, **extra):
        with connection() as c:
            c.execute("UPDATE conversation_turns SET attempt=gen_random_uuid()")
        raise Problem("LLM_UNAVAILABLE", "down", 503)

    with pytest.raises(Problem):
        send(buyer, service, conv, runner)
    assert notices(conv) == []


# --- retry --------------------------------------------------------------------------------------


def test_a_retry_removes_the_notice_and_the_answer_leaves_one_real_reply(buyer, service, conv):
    body = MessageRequest(text="Find me milk.", idempotency_key=str(uuid4()))
    with pytest.raises(Problem):
        conversations.message(buyer, conv, body, service, failing())
    assert len(notices(conv)) == 1
    conversations.enqueue(buyer, conv, body)  # the retry route
    assert notices(conv) == [], "the notice stays while the retry runs"
    runner = answering("Here is your answer.")
    result = conversations.message(buyer, conv, body, service, runner)
    assert [(m["role"], m["text"], m["notice"]) for m in result["messages"]] == [
        ("user", "Find me milk.", None),
        ("assistant", "Here is your answer.", None),
    ]
    assert result["retry_message"] is None


def test_repeated_failures_leave_one_notice_per_failed_turn(buyer, service, conv):
    body = MessageRequest(text="Find me milk.", idempotency_key=str(uuid4()))
    for _ in range(4):
        with pytest.raises(Problem):
            conversations.message(buyer, conv, body, service, failing())
        assert len(notices(conv)) == 1
        assert [m["role"] for m in stored(conv)].count("user") == 1
    conversations.message(buyer, conv, body, service, answering())
    assert notices(conv) == [] and [m["role"] for m in stored(conv)] == ["user", "assistant"]


def test_the_model_never_sees_the_notice(buyer, service, conv):
    first = MessageRequest(text="Find me milk.", idempotency_key=str(uuid4()))
    with pytest.raises(Problem):
        conversations.message(buyer, conv, first, service, failing())
    runner = answering()
    conversations.message(buyer, conv, first, service, runner)  # retried and answered
    second = MessageRequest(text="And cream.", idempotency_key=str(uuid4()))
    with pytest.raises(Problem):
        conversations.message(buyer, conv, second, service, failing())
    # a worker that runs the failed turn again gets the earlier exchange without any notice
    runner2 = answering()
    conversations.message(buyer, conv, second, service, runner2)
    roles = [(m["role"], m["content"]) for m in runner2.seen[0]]
    assert (EN in [content for _, content in roles]) is False
    assert roles[-1] == ("user", "And cream.")


def test_a_new_message_is_refused_until_the_failed_one_is_retried_and_the_notice_stays(buyer, service, conv):
    body = MessageRequest(text="Find me milk.", idempotency_key=str(uuid4()))
    with pytest.raises(Problem):
        conversations.message(buyer, conv, body, service, failing())
    with pytest.raises(Problem) as refused:
        conversations.enqueue(buyer, conv, MessageRequest(text="Other.", idempotency_key=str(uuid4())))
    assert refused.value.code == "RETRY_PREVIOUS_MESSAGE"
    assert len(notices(conv)) == 1


def test_each_language_is_used_for_the_failed_turns_own_message(buyer, service):
    for text, expected in [
        ("Tarvitsen maitoa hotellille, kiitos.", NOTICE_TEXT["fi"]),
        ("Jag behöver mjölk och grädde, tack.", NOTICE_TEXT["sv"]),
        ("I need milk for the hotel.", NOTICE_TEXT["en"]),
    ]:
        cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
        with pytest.raises(Problem):
            send(buyer, service, cid, failing(), text=text)
        assert notices(cid)[0]["text"] == expected


# --- the HTTP view ------------------------------------------------------------------------------


def signed(client):
    result = client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert result.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": result.json()["csrf_token"]}


def test_the_conversation_response_carries_the_notice_and_the_retry_route_still_works(service):
    with TestClient(create_app(service)) as client:
        headers = signed(client)
        cid = client.post(
            "/api/conversations", headers=headers, json={"idempotency_key": str(uuid4())}
        ).json()["id"]
        key = str(uuid4())
        url = f"/api/conversations/{cid}/messages"
        body = {"text": "Haluan tilata maitoa.", "idempotency_key": key}
        assert client.post(url, headers=headers, json=body).status_code == 200
        with pytest.raises(Problem):
            run_once(service, failing())
        view = client.get(f"/api/conversations/{cid}", headers=headers).json()
        ConversationResponse.model_validate(view)
        assert [(m["role"], m["notice"]) for m in view["messages"]] == [
            ("user", None),
            ("assistant", "provider_unavailable"),
        ]
        assert view["messages"][1]["text"] == NOTICE_TEXT["fi"]
        assert view["retry_message"]["idempotency_key"] == key and view["busy"] is False
        retry = client.post(url, headers=headers, json=body)  # the UI's retry: same key, same body
        assert retry.status_code == 200
        assert [m["role"] for m in retry.json()["messages"]] == ["user"]  # the notice is gone
        run_once(service, answering("Valmis."))
        done = client.get(f"/api/conversations/{cid}", headers=headers).json()
        assert [(m["role"], m["notice"], m["text"]) for m in done["messages"]][1:] == [
            ("assistant", None, "Valmis.")
        ]


# --- the migration ------------------------------------------------------------------------------


def test_migration_024_adds_one_nullable_column():
    from pathlib import Path

    from aimo.schema_state import MANIFEST

    text = Path("migrations/024_message_notice.sql").read_text()
    statements = [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("--")
    ]
    assert statements == ["ALTER TABLE conversation_messages ADD COLUMN notice text;"]
    assert MANIFEST["024_message_notice.sql"] == [("column", "conversation_messages", "notice")]
    assert "024_message_notice" in Path("migrations/README.md").read_text()
    with connection() as c:
        column = c.execute(
            """SELECT data_type, is_nullable, column_default FROM information_schema.columns
            WHERE table_name='conversation_messages' AND column_name='notice'"""
        ).fetchone()
    assert (column["data_type"], column["is_nullable"], column["column_default"]) == (
        "text",
        "YES",
        None,
    )
