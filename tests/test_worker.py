from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from aimo import conversations
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest
from aimo.db import Problem, close_pools, connection, now
from aimo.worker import run_once


def queued(buyer):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    body = MessageRequest(text="Plan lunch", idempotency_key=str(uuid4()))
    data = conversations.enqueue(buyer, cid, body)
    assert data["busy"] and len(data["messages"]) == 1
    return cid, body


def test_queue_survives_api_restart_and_duplicate_submission(buyer, service):
    cid, body = queued(buyer)
    close_pools()
    assert conversations.enqueue(buyer, cid, body)["busy"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: conversations.claim_turn(), range(2)))
    assert sum(turn is not None for turn in claims) == 1
    conversations.execute_turn(
        next(t for t in claims if t), service, lambda *args: AgentTurn(text="What date?")
    )
    assert not run_once(service)
    data = conversations.detail(buyer, cid)
    assert not data["busy"] and len(data["messages"]) == 2


def test_killed_worker_reclaimed_and_old_attempt_cannot_publish(buyer, service):
    cid, _ = queued(buyer)
    old = conversations.claim_turn()
    with connection() as c:
        c.execute(
            "UPDATE conversation_turns SET lease_until=%s WHERE id=%s",
            (now() - timedelta(seconds=1), old["id"]),
        )
    new = conversations.claim_turn()
    assert new["attempt"] != old["attempt"]
    with pytest.raises(Problem) as error:
        conversations.execute_turn(old, service, lambda *args: AgentTurn(text="stale"))
    assert error.value.code == "TURN_REPLACED"
    conversations.execute_turn(new, service, lambda *args: AgentTurn(text="current"))
    assert conversations.detail(buyer, cid)["messages"][-1]["text"] == "current"


def test_revoked_customer_job_fails_without_calling_provider(buyer, service):
    queued(buyer)
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id=%s", (buyer["id"],))
    with pytest.raises(Problem) as error:
        run_once(service, lambda *args: pytest.fail("must not invoke provider"))
    assert error.value.code == "UNAUTHENTICATED"
    with connection() as c:
        assert c.execute("SELECT state FROM conversation_turns").fetchone()["state"] == "failed"


def test_crash_retries_bounded_and_customer_can_retry(buyer, service):
    cid, body = queued(buyer)
    for _ in range(3):
        assert conversations.claim_turn()
        with connection() as c:
            c.execute(
                "UPDATE conversation_turns SET lease_until=%s", (now() - timedelta(seconds=1),)
            )
    assert conversations.claim_turn() is None
    data = conversations.detail(buyer, cid)
    assert not data["busy"] and data["retry_message"]["idempotency_key"] == body.idempotency_key
    conversations.enqueue(buyer, cid, body)
    assert run_once(service, lambda *args: AgentTurn(text="Recovered"))
    assert len(conversations.detail(buyer, cid)["messages"]) == 2



def test_execution_and_failure_state_errors_are_both_logged_without_masking_original(
    buyer, service, monkeypatch, caplog
):
    import json
    from contextlib import contextmanager

    cid, _ = queued(buyer)
    turn = conversations.claim_turn()
    original = RuntimeError("private-runner-error")

    @contextmanager
    def broken_storage():
        raise RuntimeError("private-database-url")
        yield

    def runner(*args, **kwargs):
        monkeypatch.setattr(conversations, "connection", broken_storage)
        raise original

    with caplog.at_level("INFO", logger="aimo.operations"), pytest.raises(RuntimeError) as caught:
        conversations.execute_turn(turn, service, runner)
    assert caught.value is original
    rows = [json.loads(r.message) for r in caplog.records if r.name == "aimo.operations"]
    failed = [r for r in rows if r["event"] in {"chat.execution_failed", "chat.failure_state_failed"}]
    assert len(failed) == 2
    assert all(r["turn_id"] == str(turn["id"]) and r["conversation_id"] == cid for r in failed)
    assert "private-" not in json.dumps(rows)


def test_worker_persistence_logs_final_state_with_claim_correlation(buyer, service, caplog):
    import json

    cid, _ = queued(buyer)
    with caplog.at_level("INFO", logger="aimo.operations"):
        assert run_once(service, lambda *args: AgentTurn(text="private-answer"))
    rows = [json.loads(r.message) for r in caplog.records if r.name == "aimo.operations"]
    claimed = next(r for r in rows if r["event"] == "worker.claimed")
    saved = next(r for r in rows if r["event"] == "chat.persisted")
    assert claimed["conversation_id"] == saved["conversation_id"] == cid
    assert claimed["attempt_id"] == saved["attempt_id"]
    assert claimed["queue_age_ms"] >= 0 and claimed["lease_remaining_ms"] > 0
    assert saved["state"] == "complete" and not saved["partial"]
    assert "private-answer" not in json.dumps(rows)
