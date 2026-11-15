# ruff: noqa: F811
"""Every path that creates or replaces a cart basket is serialized (8c findings F1 to F3).

The basket, the cancellation of older open baskets and the link message are written in ONE transaction
under the buyer lock; the already-ordered state, the busy state and the plan the caller read are checked
again inside it. Real concurrency (threads and forked processes, many rounds) and a deterministic
interleave: a confirm that lands between the supplier lookup and the basket's creation.
"""

import multiprocessing
import threading
from uuid import uuid4

import pytest
from test_cart_auto_prepare import auto, baskets, data, edited_turn, more, state  # noqa: F401
from test_cart_edit import lines_of, put  # noqa: F401
from test_cart_ordered import press  # noqa: F401
from test_draft_cart_purchase import CUSTOMER_PLAN_TURN, chat, plan  # noqa: F401

from aimo import approval_workflow as workflow
from aimo import cart_purchase
from aimo.chat_schemas import CartEditRequest
from aimo.db import Problem, close_pools, connection

ROUNDS = 30


def counts(cid):
    with connection() as c:
        open_now = c.execute(
            """SELECT count(DISTINCT p.id) AS n FROM conversation_messages m JOIN proposals p ON p.id=m.proposal_id
            WHERE m.conversation_id=%s AND p.order_id IS NULL AND NOT EXISTS
            (SELECT 1 FROM order_request_cancellations x WHERE x.proposal_id=p.id)""",
            (cid,),
        ).fetchone()["n"]
        orders = c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]
    return open_now, orders


def current(d):
    live = [b for b in baskets(d) if state(b) != "cancelled"]
    assert len(live) == 1, [state(b) for b in baskets(d)]
    return live[0]


def together(*jobs):
    gate = threading.Barrier(len(jobs))
    out = [None] * len(jobs)

    def run(i, job):
        gate.wait()
        out[i] = job()

    threads = [threading.Thread(target=run, args=(i, j)) for i, j in enumerate(jobs)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return out


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_two_edits_of_different_products_at_once_lose_neither(auto, round_):
    conv = auto.new_conversation()
    conv(*CUSTOMER_PLAN_TURN)
    a, b = together(
        lambda: put(auto, [("pasta", 3)], cid=conv.cid),
        lambda: put(auto, [("eggs", 7)], cid=conv.cid),
    )
    assert {a.status_code, b.status_code} == {200}, (a.text, b.text)
    live = current(data(auto, conv.cid))
    assert lines_of(live)["meal-pasta"] == "3" and lines_of(live)["meal-eggs"] == "7"
    assert counts(conv.cid)[0] == 1


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_two_edits_of_one_product_at_once_leave_exactly_one_open_basket(auto, round_):
    conv = auto.new_conversation()
    conv(*CUSTOMER_PLAN_TURN)
    a, b = together(
        lambda: put(auto, [("pepper", 3)], cid=conv.cid),
        lambda: put(auto, [("pepper", 4)], cid=conv.cid),
    )
    assert {a.status_code, b.status_code} == {200}, (a.text, b.text)
    live = current(data(auto, conv.cid))
    assert lines_of(live)["meal-pepper"] in ("3", "4")
    assert counts(conv.cid)[0] == 1


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_two_presses_and_an_edit_at_once_leave_exactly_one_open_basket(auto, round_):
    conv = auto.new_conversation()
    conv(*CUSTOMER_PLAN_TURN)

    def pressed():
        return auto.client.post(
            f"/api/conversations/{conv.cid}/prepare-from-cart", headers=auto.headers,
            json={"delivery_date": "2099-01-05", "destination": "hotel-helsinki",
                  "request_id": str(uuid4())},
        )  # fmt: skip

    results = together(pressed, pressed, lambda: put(auto, [("pepper", 3)], cid=conv.cid))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert counts(conv.cid)[0] == 1
    current(data(auto, conv.cid))


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_a_confirm_racing_two_edits_orders_at_most_once(auto, round_):
    conv = auto.new_conversation()
    first = conv(*CUSTOMER_PLAN_TURN)["purchases"][0]

    def confirm():
        return auto.client.post(
            f"/api/purchases/{first['proposal_id']}/confirm", headers=auto.headers,
            json={"proposal_id": first["proposal_id"], "revision": first["revision"],
                  "idempotency_key": str(uuid4())},
        )  # fmt: skip

    together(confirm, lambda: put(auto, [("pepper", 3)], cid=conv.cid),
             lambda: put(auto, [("pasta", 5)], cid=conv.cid))  # fmt: skip
    open_now, orders = counts(conv.cid)
    assert orders <= 1 and open_now <= 1
    if orders == 1:  # the order won: whatever came after it may not stay open next to it
        with connection() as c:
            placed = c.execute("SELECT proposal_id FROM orders").fetchone()["proposal_id"]
        assert str(placed) == first["proposal_id"]


def _child(args, queue):
    from aimo.chat_schemas import CartEditRequest as Edit

    identity, cid, product, packs, service = args
    close_pools()  # a forked child must not reuse the parent's connections
    try:
        out = cart_purchase.edit_cart(
            identity,
            cid,
            Edit(request_id=str(uuid4()), lines=[{"product_id": product, "sales_quantity": packs}]),
            service,
        )
        queue.put(("ok", out["proposal"]["proposal_id"]))
    except Problem as exc:
        queue.put((exc.code, None))


@pytest.mark.parametrize("round_", range(10))
def test_two_edits_from_two_processes_lose_neither(auto, buyer, round_):
    conv = auto.new_conversation()
    conv(*CUSTOMER_PLAN_TURN)
    close_pools()
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    procs = [
        ctx.Process(target=_child, args=((buyer, conv.cid, pid, packs, auto.service), queue))
        for pid, packs in (("meal-pasta", 3), ("meal-eggs", 7))
    ]
    [p.start() for p in procs]
    results = [queue.get(timeout=60) for _ in procs]
    [p.join(timeout=30) for p in procs]
    assert [r[0] for r in results] == ["ok", "ok"], results
    live = current(data(auto, conv.cid))
    assert lines_of(live)["meal-pasta"] == "3" and lines_of(live)["meal-eggs"] == "7"
    assert counts(conv.cid)[0] == 1


# --- F3: the already-ordered state is checked again where the basket is created ----------------------


def confirm_during_the_supplier_lookup(auto, monkeypatch, first):
    """Deterministic interleave: the customer's confirm lands after the caller's early checks and
    before the basket is created."""
    real = workflow.build_snapshot
    done = []
    started = []

    def slow(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        if not started:
            started.append(True)  # the confirm itself looks things up again: do this only once
            done.append(
                auto.client.post(
                    f"/api/purchases/{first['proposal_id']}/confirm",
                    headers=auto.headers,
                    json={
                        "proposal_id": first["proposal_id"],
                        "revision": first["revision"],
                        "idempotency_key": str(uuid4()),
                    },
                )  # fmt: skip
            )
        return snapshot

    monkeypatch.setattr(workflow, "build_snapshot", slow)
    return done


def test_a_confirm_between_the_check_and_the_basket_refuses_the_press(auto, monkeypatch):
    first = auto.turn(*CUSTOMER_PLAN_TURN)["purchases"][0]
    done = confirm_during_the_supplier_lookup(auto, monkeypatch, first)
    sent = press(auto)
    assert done[0].status_code == 200
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "BASKET_ALREADY_ORDERED"
    assert counts(auto.turn.cid) == (0, 1)


def test_a_confirm_between_the_check_and_the_basket_refuses_the_edit(auto, monkeypatch):
    first = auto.turn(*CUSTOMER_PLAN_TURN)["purchases"][0]
    done = confirm_during_the_supplier_lookup(auto, monkeypatch, first)
    sent = put(auto, [("pepper", 3)])
    assert done[0].status_code == 200
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "BASKET_ALREADY_ORDERED"
    assert counts(auto.turn.cid) == (0, 1)


def test_a_confirm_between_the_check_and_the_basket_stops_the_automatic_prepare(auto, monkeypatch):
    first = auto.turn(*CUSTOMER_PLAN_TURN)["purchases"][0]
    done = confirm_during_the_supplier_lookup(auto, monkeypatch, first)
    d = edited_turn(auto, more(("20", "12", "6", "4", "0.4")), "a bit more pepper")
    assert done[0].status_code == 200 and not d["busy"]  # the turn itself is fine
    assert counts(auto.turn.cid) == (0, 1)  # but no second basket next to the order


def test_the_busy_state_is_checked_where_the_basket_is_created(auto, monkeypatch):
    auto.turn(*CUSTOMER_PLAN_TURN)
    real = workflow.build_snapshot
    queued = []

    def slow(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        if not queued:  # a chat message arrives while the supplier is being asked
            queued.append(
                auto.client.post(
                    f"/api/conversations/{auto.turn.cid}/messages",
                    headers=auto.headers,
                    json={"text": "wait", "idempotency_key": str(uuid4())},
                )  # fmt: skip
            )
        return snapshot

    monkeypatch.setattr(workflow, "build_snapshot", slow)
    sent = put(auto, [("pepper", 3)])
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "CONVERSATION_BUSY"
    assert counts(auto.turn.cid)[0] == 1  # the old basket stays the only open one


# --- strict integers -----------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False, "3", "03", 3.0, None])
def test_sales_quantity_is_a_strict_integer(auto, value):
    auto.turn(*CUSTOMER_PLAN_TURN)
    sent = auto.client.put(
        f"/api/conversations/{auto.turn.cid}/cart", headers=auto.headers,
        json={"request_id": str(uuid4()), "lines": [{"product_id": "meal-pepper", "sales_quantity": value}]},
    )  # fmt: skip
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "VALIDATION_ERROR"
    assert counts(auto.turn.cid)[0] == 1


def test_the_model_validator_itself_is_strict():
    with pytest.raises(Exception):
        CartEditRequest(
            request_id="12345678", lines=[{"product_id": "meal-pepper", "sales_quantity": True}]
        )
