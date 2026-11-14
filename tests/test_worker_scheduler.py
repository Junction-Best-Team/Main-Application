"""The scheduler pass inside the worker loop: chat first, one step per iteration, never fatal."""

from uuid import uuid4

import pytest
from test_scheduler_engine import at, one, run_of, scheduled

from aimo import conversations, scheduler, worker
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest


@pytest.fixture(autouse=True)
def fresh_throttle(monkeypatch):
    monkeypatch.setitem(worker.scheduler_state, "materialised", float("-inf"))


@pytest.fixture
def due_schedule(buyer, service, placed_order, monkeypatch):
    s = scheduled(buyer, service, placed_order)
    real = scheduler.run_due_schedules
    monkeypatch.setattr(
        scheduler, "run_due_schedules", lambda svc, **kw: real(svc, now=at(), **kw)
    )  # the test clock: 07:00 Helsinki today
    return s


def test_a_waiting_chat_turn_goes_before_the_schedules(buyer, service, due_schedule):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    conversations.enqueue(
        buyer, cid, MessageRequest(text="Plan lunch", idempotency_key=str(uuid4()))
    )
    assert worker.work_once(service, lambda *a: AgentTurn(text="Which date?")) is True
    assert run_of(due_schedule) is None  # the schedule waited one iteration
    assert worker.work_once(service) is True
    assert run_of(due_schedule)["status"] == "prepared"


def test_without_chat_work_the_schedules_advance_one_step_per_iteration(service, due_schedule):
    assert worker.work_once(service) is True and run_of(due_schedule)["status"] == "prepared"
    assert worker.work_once(service) is True and run_of(due_schedule)["status"] == "committed"
    assert worker.work_once(service) is False


def test_the_due_scan_is_throttled_but_claimed_runs_are_not(service, due_schedule, monkeypatch):
    calls = []
    real = scheduler.run_due_schedules

    def spy(svc, **kw):
        calls.append(kw["materialise_first"])
        return real(svc, **kw)

    monkeypatch.setattr(scheduler, "run_due_schedules", spy)
    worker.work_once(service)  # scans, prepares
    worker.work_once(service)  # no scan, commits the claimed run
    worker.work_once(service)
    assert calls == [True, False, False]


def test_a_failing_scheduler_never_stops_the_worker(service, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("scheduler tables are missing")

    monkeypatch.setattr(scheduler, "run_due_schedules", broken)
    assert worker.work_once(service) is False
    assert any("scheduler.iteration_failed" in r.getMessage() for r in caplog.records)


def test_a_chat_turn_still_runs_when_the_scheduler_is_broken(buyer, service, monkeypatch):
    monkeypatch.setattr(
        scheduler, "run_due_schedules", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    conversations.enqueue(
        buyer, cid, MessageRequest(text="Plan lunch", idempotency_key=str(uuid4()))
    )
    assert worker.work_once(service, lambda *a: AgentTurn(text="ok")) is True
    assert one("SELECT count(*) AS n FROM conversation_messages WHERE role='assistant'")["n"] == 1
