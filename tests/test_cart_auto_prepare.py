# ruff: noqa: F811
"""Q-123d: the cart is always the exact basket. A chat turn that changed the cart prepares it again.

Every rule the owner/coordinator named: edits create new baskets (older open ones are cancelled in the
same transaction, never one with an order), no basket without a change, an empty cart has none, a
failure never fails the turn, date and destination come from the latest basket (else tomorrow Helsinki and
the first policy destination), the model's own prepare in a turn suppresses it, and a stale confirm gets
"revised" with nothing ordered.
"""

import threading
from datetime import date, timedelta
from uuid import uuid4

import pytest
from test_draft_cart_purchase import (  # noqa: F401  (the harness and its fixtures)
    CUSTOMER_PLAN_TURN,
    MATCH,
    NAMES,
    call,
    chat,
    plan,
    prepare_only,
    say,
    shows_draft_panel,
    tool_reply,
)

from aimo import scheduler
from aimo.config import settings
from aimo.db import Problem, connection

TOMORROW = str(scheduler.helsinki_today() + timedelta(days=1))


@pytest.fixture
def auto(chat, monkeypatch):
    monkeypatch.setattr(settings(), "cart_auto_prepare", True)
    return chat


def data(chat, cid=None):
    return chat.client.get(f"/api/conversations/{cid or chat.turn.cid}").json()


def more(amounts):
    """The same plan with other amounts (a customer edit: portions changed)."""
    p = plan()
    for item, amount in zip(p["ingredients"], amounts):
        item["amount"] = amount
    return p


EDIT = ("20", "12", "6", "4", "0.4")


def edited_turn(chat, p, text="a bit more pepper"):
    return chat.turn(text, tool_reply(call("publish_meal_plan", p)), say("Updated the plan."))


def baskets(d):
    return d["purchases"]


def state(basket):
    return basket["approval_status"]


def test_a_plan_the_model_only_published_is_prepared_for_tomorrow_in_helsinki(auto):
    d = auto.turn(*CUSTOMER_PLAN_TURN)
    assert len(baskets(d)) == 1 and not shows_draft_panel(d)
    basket = baskets(d)[0]
    assert basket["request"]["delivery_date"] == TOMORROW
    assert basket["request"]["destination"] == "hotel-helsinki"
    assert basket["order_id"] is None  # prepared only; the customer confirms
    assert d["messages"][-1]["proposal_id"] == basket["proposal_id"]
    assert d["draft_cart"] is None  # the exact basket replaces the display-only draft


def test_an_edit_makes_a_new_basket_and_cancels_the_older_open_one(auto):
    first = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]["proposal_id"]
    d = edited_turn(auto, more(EDIT))
    by_id = {b["proposal_id"]: b for b in baskets(d)}
    assert len(by_id) == 2
    latest = d["messages"][-1]["proposal_id"]
    assert (
        latest != first
        and state(by_id[first]) == "cancelled"
        and state(by_id[latest]) != "cancelled"
    )
    open_now = [b for b in baskets(d) if state(b) != "cancelled"]
    assert [b["proposal_id"] for b in open_now] == [latest]  # one confirmable basket, never two
    assert {
        i["product_id"]: i["quantity"]["requested_amount"]
        for i in by_id[latest]["snapshot"]["lines"]
    }["meal-pepper"] == "0.4"
    with connection() as c:
        reason = c.execute(
            "SELECT reason FROM order_request_cancellations WHERE proposal_id=%s", (first,)
        ).fetchone()["reason"]
    assert reason == "customer_revised"


def test_no_basket_without_a_change(auto):
    first = auto.turn(*CUSTOMER_PLAN_TURN)
    again = auto.turn("thanks", say("You are welcome."))  # text only: the plan is not re-sent
    assert [b["proposal_id"] for b in baskets(again)] == [b["proposal_id"] for b in baskets(first)]
    same = edited_turn(auto, plan(), "same plan again")  # republished unchanged
    assert [b["proposal_id"] for b in baskets(same)] == [b["proposal_id"] for b in baskets(first)]
    assert state(baskets(same)[0]) != "cancelled"


def test_an_empty_cart_has_no_basket_and_keeps_the_draft(auto):
    p = plan()
    for item in p["ingredients"]:
        item["product_id"] = None
    d = auto.turn("200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", p)),
                  say("Nothing matched yet."))  # fmt: skip
    assert baskets(d) == [] and d["draft_cart"] is not None and shows_draft_panel(d)


def test_unmatched_items_are_left_out_of_the_basket_and_named_in_the_reply(auto):
    p = plan()
    p["ingredients"][-1]["product_id"] = None
    d = auto.turn("200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", p)),
                  say("Pepper is still open."))  # fmt: skip
    assert len(baskets(d)[0]["snapshot"]["lines"]) == 4
    assert "Not included: pepper" in d["messages"][-1]["text"]


def test_the_model_preparing_in_the_turn_suppresses_the_auto_prepare(auto):
    d = auto.turn("200 portions of carbonara", *MATCH, tool_reply(call("publish_meal_plan", plan())),
                  *prepare_only())  # fmt: skip
    assert len(baskets(d)) == 1 and state(baskets(d)[0]) != "cancelled"


def test_a_failure_never_fails_the_turn_and_the_draft_stays(auto, monkeypatch):
    def down(*args, **kwargs):
        raise Problem("UPSTREAM_UNAVAILABLE", "Supplier lookup failed.", 503)

    monkeypatch.setattr(auto.service, "prepare_order", down)
    d = auto.turn(*CUSTOMER_PLAN_TURN)
    assert d["messages"][-1]["text"].startswith("Here is the plan")  # the reply is intact
    assert baskets(d) == [] and shows_draft_panel(d) and not d["busy"]
    assert d["activity"]["state"] == "complete"


def test_date_and_destination_come_from_the_latest_basket(auto):
    first = auto.turn(*CUSTOMER_PLAN_TURN)
    assert baskets(first)[0]["request"]["delivery_date"] == TOMORROW
    later = str(date.today() + timedelta(days=6))
    sent = auto.client.post(
        f"/api/conversations/{auto.turn.cid}/prepare-from-cart", headers=auto.headers,
        json={"delivery_date": later, "destination": "hotel-helsinki", "request_id": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 200
    d = edited_turn(auto, more(EDIT))  # the next edit keeps the date the customer chose
    latest = next(b for b in baskets(d) if b["proposal_id"] == d["messages"][-1]["proposal_id"])
    assert latest["request"]["delivery_date"] == later


def test_only_baskets_of_this_conversation_are_cancelled(auto):
    mine = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]["proposal_id"]
    other = auto.new_conversation()
    theirs = baskets(other(*CUSTOMER_PLAN_TURN))[0]["proposal_id"]
    edited_turn(auto, more(EDIT))
    seen = {b["proposal_id"]: b for b in baskets(data(auto, other.cid))}
    assert state(seen[theirs]) != "cancelled"
    assert state({b["proposal_id"]: b for b in baskets(data(auto))}[mine]) == "cancelled"


def test_a_basket_with_an_order_is_never_cancelled(auto):
    first = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]
    sent = auto.client.post(
        f"/api/purchases/{first['proposal_id']}/confirm", headers=auto.headers,
        json={"proposal_id": first["proposal_id"], "revision": first["revision"],
              "idempotency_key": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 200, sent.text
    d = edited_turn(auto, more(EDIT))
    by_id = {b["proposal_id"]: b for b in baskets(d)}
    assert (
        by_id[first["proposal_id"]]["order_id"]
        and state(by_id[first["proposal_id"]]) != "cancelled"
    )
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 1


def test_a_stale_confirm_gets_revised_and_nothing_is_ordered(auto):
    first = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]
    edited_turn(auto, more(EDIT))
    sent = auto.client.post(
        f"/api/purchases/{first['proposal_id']}/confirm", headers=auto.headers,
        json={"proposal_id": first["proposal_id"], "revision": first["revision"],
              "idempotency_key": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "REQUEST_REVISED"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


def test_reload_shows_the_same_card(auto):
    d = auto.turn(*CUSTOMER_PLAN_TURN)
    assert data(auto) == data(auto) and data(auto)["purchases"] == d["purchases"]
    assert data(auto)["draft_cart"] is None


def test_a_confirm_racing_the_revision_gives_one_order_at_most(auto):
    first = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]
    results = {}
    gate = threading.Barrier(2)

    def confirm():
        gate.wait()
        results["confirm"] = auto.client.post(
            f"/api/purchases/{first['proposal_id']}/confirm", headers=auto.headers,
            json={"proposal_id": first["proposal_id"], "revision": first["revision"],
                  "idempotency_key": str(uuid4())},
        )  # fmt: skip

    def revise():
        gate.wait()
        results["revise"] = auto.client.post(
            f"/api/conversations/{auto.turn.cid}/prepare-from-cart", headers=auto.headers,
            json={"delivery_date": str(date.today() + timedelta(days=4)),
                  "destination": "hotel-helsinki", "request_id": str(uuid4())},
        )  # fmt: skip

    threads = [threading.Thread(target=confirm), threading.Thread(target=revise)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with connection() as c:
        orders = c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]
        open_baskets = c.execute(
            """SELECT count(*) AS n FROM proposals p WHERE p.order_id IS NULL AND NOT EXISTS
            (SELECT 1 FROM order_request_cancellations x WHERE x.proposal_id=p.id)"""
        ).fetchone()["n"]
    assert orders <= 1
    if results["confirm"].status_code == 200:
        # The order won: the revision is refused (a second basket next to an order is never made).
        assert orders == 1 and open_baskets == 0
        assert results["revise"].status_code == 409
        assert results["revise"].json()["error"]["code"] == "BASKET_ALREADY_ORDERED"
    else:  # the revision won: "revised", nothing ordered, exactly one open basket
        assert results["revise"].status_code == 200, results["revise"].text
        assert results["confirm"].json()["error"]["code"] == "REQUEST_REVISED" and orders == 0
        assert open_baskets == 1


def test_the_switch_turns_it_off(chat, monkeypatch):
    monkeypatch.setattr(settings(), "cart_auto_prepare", False)
    d = chat.turn(*CUSTOMER_PLAN_TURN)
    assert baskets(d) == [] and shows_draft_panel(d)


def test_an_edit_after_a_text_only_turn_still_starts_from_the_cart(auto):
    first = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]["proposal_id"]
    auto.turn("thanks", say("You are welcome."))
    d = edited_turn(auto, more(EDIT))  # products are verified again from the stored plan
    latest = d["messages"][-1]["proposal_id"]
    by_id = {b["proposal_id"]: b for b in baskets(d)}
    assert latest != first and state(by_id[first]) == "cancelled"


def test_a_basket_the_model_prepares_later_also_replaces_the_open_one(auto):
    first = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]["proposal_id"]
    d = auto.turn("make it 0.4 pepper", tool_reply(call("publish_meal_plan", more(EDIT))),
                  tool_reply(call("prepare_order", prepared_for(EDIT))), say("Review the basket."))  # fmt: skip
    by_id = {b["proposal_id"]: b for b in baskets(d)}
    assert state(by_id[first]) == "cancelled"
    assert [b["proposal_id"] for b in baskets(d) if state(b) != "cancelled"] == [
        d["messages"][-1]["proposal_id"]
    ]


def prepared_for(amounts):
    from test_draft_cart_purchase import prepared

    p = prepared()
    p["delivery_date"] = TOMORROW
    for line, amount in zip(p["lines"], amounts):
        line["amount"] = amount
    return p
