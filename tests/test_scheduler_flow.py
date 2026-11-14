"""WS-E end to end, fixture mode: the customer's routes, the worker's scheduler step and the chat.

Two whole stories, driven the way the product runs them: the customer acts through the HTTP routes
(session cookie, Origin, CSRF); the worker step `worker.work_once` runs the scheduler against a
test clock (07:00 Helsinki today); the agent turn uses a fake model runner. Every order is a mock
("Accepted by demo order service"). No live supplier traffic, no model call.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_http import login
from test_scheduler_engine import at, widen_scope

from aimo import auth, scheduler, worker
from aimo.api import create_app
from aimo.chat_schemas import AgentTurn
from aimo.db import connection
from aimo.schemas import PrepareRequest

DAILY = {"kind": "days", "interval": 1}


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """The worker's scheduler step runs at 07:00 Helsinki on clock["day"], whatever the real time."""
    state = {"day": date.today()}
    real = scheduler.run_due_schedules
    monkeypatch.setattr(
        scheduler, "run_due_schedules", lambda svc, **kw: real(svc, now=at(state["day"]), **kw)
    )
    monkeypatch.setitem(worker.scheduler_state, "materialised", float("-inf"))
    return state


def tick(service, runner=None, times=6):
    """Worker iterations until nothing is left to do."""
    runner = runner or (lambda *a: AgentTurn(text="Here are two replacements with their prices."))
    worker.scheduler_state["materialised"] = float("-inf")  # the scan interval has passed
    for _ in range(times):
        worker.work_once(service, runner)


def post(http, headers, path, body=None):
    r = http.post(path, headers=headers, json=body or {})
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
    return r.json()


def get(http, path):
    r = http.get(path)
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
    return r.json()


def create_schedule(http, headers, order_id, *, rules=None, ceiling="100.00"):
    base = {
        "order_id": order_id,
        "recurrence": DAILY,
        "first_run_date": str(date.today()),
        "line_rules": rules or {},
    }
    terms = post(http, headers, "/api/schedules/preview", base)
    assert terms["policy_outcome"] == "ready_to_commit"
    return post(
        http,
        headers,
        "/api/schedules",
        base
        | {
            "price_ceiling_gross": ceiling,
            "agreed_terms_fingerprint": terms["terms_fingerprint"],
            "idempotency_key": str(uuid4()),
        },
    )


def place_order(http, headers, service, buyer, request_data, **lines):
    """A new order through the product's own confirm route (the customer's click)."""
    request_data = request_data | {"idempotency_key": str(uuid4())} | lines
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    receipt = post(
        http,
        headers,
        f"/api/purchases/{p['proposal_id']}/confirm",
        {"proposal_id": p["proposal_id"], "revision": 1, "idempotency_key": str(uuid4())},
    )
    return {"order_id": receipt["order_id"], "proposal_id": p["proposal_id"]}


def statuses(http):
    return [(o["status"], o.get("cancel_reason")) for o in get(http, "/api/orders")["items"]]


def test_a_disrupted_standing_order_is_revised_in_chat_and_restarted(
    http, service, connector, buyer, request_data, placed_order
):
    headers = login(http)
    schedule = create_schedule(http, headers, placed_order["order_id"])
    assert schedule["status"] == "active" and ("scheduled", None) in statuses(http)

    # The milk is not available on the delivery date: the run stops the schedule and starts a chat.
    connector.stock = {"464306": "0"}
    tick(service)
    stopped = get(http, f"/api/schedules/{schedule['id']}")
    assert stopped["status"] == "stopped" and stopped["stop_reason"] == "PRODUCT_UNAVAILABLE"
    run = stopped["runs"][0]
    assert run["status"] == "disrupted" and run["reason"]["lines"][0]["status"] == "unavailable"
    assert run["order_id"] is None and stopped["conversation_id"] == run["conversation_id"]
    assert ("scheduled", None) not in statuses(http)
    assert ("cancelled", "run_disrupted") in statuses(http)

    # The agent was woken by the system-authored first message and replied.
    chat = get(http, f"/api/conversations/{stopped['conversation_id']}")
    assert [m["role"] for m in chat["messages"]] == ["system", "assistant"]
    assert "unavailable" in chat["messages"][0]["text"] and chat["busy"] is False

    # The customer settles on a revised order, then restarts the schedule from it with one click.
    connector.stock = {}
    revised = place_order(
        http, headers, service, buyer, request_data,
        lines=[{"product_id": "464306", "amount": "12", "unit": "L"}],
    )  # fmt: skip
    edit = post(
        http,
        headers,
        f"/api/schedules/{schedule['id']}/preview",
        {"source_order_id": revised["order_id"]},
    )
    restarted = post(
        http,
        headers,
        f"/api/schedules/{schedule['id']}/replace",
        {
            "source_order_id": revised["order_id"],
            "agreed_terms_fingerprint": edit["terms_fingerprint"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert restarted["status"] == "active" and restarted["supersedes_id"] == schedule["id"]
    assert restarted["lines"][0]["amount"] == "12"
    assert get(http, f"/api/schedules/{schedule['id']}")["replaced_by"] == restarted["id"]

    # The restarted schedule places its order, a mock one, from the revised lines.
    tick(service)
    placed = [o for o in get(http, "/api/orders")["items"] if o["schedule_id"] == restarted["id"]]
    assert sorted(o["status"] for o in placed) == ["placed", "scheduled"]  # and tomorrow's date
    done = next(o for o in placed if o["status"] == "placed")
    with connection() as c:
        receipt = c.execute(
            "SELECT receipt FROM orders WHERE id=%s", (done["order_id"],)
        ).fetchone()["receipt"]
    assert receipt["label"] == "Accepted by demo order service"
    assert receipt["upstream_order_placed"] is False and receipt["inventory_reserved"] is False
    assert receipt["scheduled_run"]["schedule_id"] == restarted["id"]


def test_a_pause_skips_dates_and_an_accepted_substitute_keeps_the_schedule_running(
    http, service, connector, placed_order, clock
):
    widen_scope("464398")
    headers = login(http)
    rules = {"464306": {"accepted_substitutes": ["464398"], "price_range_pct": "5"}}
    options = get(http, "/api/schedules/substitute-candidates?product_id=464306")
    assert options["product_id"] == "464306" and isinstance(options["candidates"], list)
    schedule = create_schedule(http, headers, placed_order["order_id"], rules=rules)
    assert schedule["lines"][0]["accepted_substitutes"][0]["product_id"] == "464398"

    # A paused schedule skips the date: no order, no chat, still paused.
    paused = post(http, headers, f"/api/schedules/{schedule['id']}/pause")
    assert paused["status"] == "paused" and paused["paused_at"]
    tick(service)
    detail = get(http, f"/api/schedules/{schedule['id']}")
    assert [r["status"] for r in detail["runs"]] == ["skipped"] and detail[
        "conversation_id"
    ] is None
    assert detail["status"] == "paused" and ("scheduled", None) in statuses(http)

    # Resumed, the next date runs; the original is out of stock, so the accepted substitute is used.
    post(http, headers, f"/api/schedules/{schedule['id']}/resume")
    connector.stock = {"464306": "0"}
    clock["day"] = date.today() + timedelta(days=1)  # the next scheduled date
    tick(service)
    detail = get(http, f"/api/schedules/{schedule['id']}")
    newest = detail["runs"][0]
    assert detail["status"] == "active" and newest["status"] == "committed"
    assert [s["substitute_product_id"] for s in newest["substitutions"]] == ["464398"]
    assert newest["conversation_id"] is None  # a substitution is not a disruption
    row = next(o for o in get(http, "/api/orders")["items"] if o["order_id"] == newest["order_id"])
    assert row["status"] == "placed" and row["schedule_id"] == schedule["id"]
    assert Decimal(row["gross_total"]) > 0
