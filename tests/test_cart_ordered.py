# ruff: noqa: F811
"""After an order, the same cart must not make a second open basket (8c finding: double-order risk).

Pressing the cart again, a PUT /cart or an automatic prepare for the plan that was already ordered is
refused or does nothing; a NEW plan (a new customer request) starts a new cart as before. The original
press can still be replayed. The card is told it cannot be edited ("This order was already placed.").
"""

from datetime import date, timedelta
from uuid import uuid4

from test_cart_auto_prepare import (  # noqa: F401
    EDIT,
    auto,
    baskets,
    data,
    edited_turn,
    more,
    state,
)
from test_cart_edit import lines_of, put  # noqa: F401
from test_draft_cart_purchase import CUSTOMER_PLAN_TURN, chat, plan  # noqa: F401

from aimo.db import connection

LATER = str(date.today() + timedelta(days=5))


def order(auto):
    first = baskets(auto.turn(*CUSTOMER_PLAN_TURN))[0]
    sent = auto.client.post(
        f"/api/purchases/{first['proposal_id']}/confirm", headers=auto.headers,
        json={"proposal_id": first["proposal_id"], "revision": first["revision"],
              "idempotency_key": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 200, sent.text
    return first, sent.json()["order_id"]


def press(auto, key=None, day=LATER):
    return auto.client.post(
        f"/api/conversations/{auto.turn.cid}/prepare-from-cart", headers=auto.headers,
        json={"delivery_date": day, "destination": "hotel-helsinki", "request_id": key or str(uuid4())},
    )  # fmt: skip


def orders():
    with connection() as c:
        return c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]


def test_pressing_the_cart_again_after_an_order_is_refused(auto):
    first, order_id = order(auto)
    sent = press(auto)
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "BASKET_ALREADY_ORDERED"
    assert sent.json()["error"]["details"]["order_id"] == order_id
    assert "already placed" in sent.json()["error"]["message"]
    assert [b["proposal_id"] for b in baskets(data(auto))] == [first["proposal_id"]]
    assert orders() == 1


def test_editing_a_pack_count_after_an_order_is_refused(auto):
    first, order_id = order(auto)
    sent = put(auto, [("pepper", 3)])
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "BASKET_ALREADY_ORDERED"
    assert sent.json()["error"]["details"]["order_id"] == order_id
    assert len(baskets(data(auto))) == 1


def test_the_automatic_prepare_does_nothing_for_the_plan_that_was_ordered(auto):
    first, _ = order(auto)
    d = edited_turn(auto, plan(), "same plan again")  # the model republishes the ordered cart
    assert [b["proposal_id"] for b in baskets(d)] == [first["proposal_id"]]
    assert orders() == 1


def test_a_new_plan_after_an_order_starts_a_new_cart_as_before(auto):
    first, _ = order(auto)
    d = edited_turn(auto, more(EDIT), "now a bit more pepper, as a new order")
    open_now = [b for b in baskets(d) if state(b) != "cancelled" and not b["order_id"]]
    assert len(open_now) == 1 and open_now[0]["proposal_id"] != first["proposal_id"]
    assert [b for b in baskets(d) if b["proposal_id"] == first["proposal_id"]][0]["order_id"]
    # the new cart can be edited again
    assert put(auto, [("pepper", 5)]).status_code == 200


def test_replaying_the_original_press_after_the_order_returns_that_basket(auto):
    auto.turn(*CUSTOMER_PLAN_TURN)
    key = str(uuid4())
    made = press(auto, key, str(date.today() + timedelta(days=2))).json()["proposal"]
    sent = auto.client.post(
        f"/api/purchases/{made['proposal_id']}/confirm", headers=auto.headers,
        json={"proposal_id": made["proposal_id"], "revision": made["revision"],
              "idempotency_key": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 200, sent.text
    again = press(auto, key, str(date.today() + timedelta(days=2)))
    assert (
        again.status_code == 200 and again.json()["proposal"]["proposal_id"] == made["proposal_id"]
    )
    assert orders() == 1


def test_the_card_is_told_it_cannot_be_edited_after_an_order(auto):
    start = auto.turn(*CUSTOMER_PLAN_TURN)
    assert data(auto)["cart_editable"] is True and baskets(start)
    first = baskets(start)[0]
    auto.client.post(
        f"/api/purchases/{first['proposal_id']}/confirm", headers=auto.headers,
        json={"proposal_id": first["proposal_id"], "revision": first["revision"],
              "idempotency_key": str(uuid4())},
    )  # fmt: skip
    d = data(auto)
    assert d["cart_editable"] is False and d["cart_edit_reason"] == "This order was already placed."
    edited_turn(auto, more(EDIT), "a new request")  # a new plan: editable again
    assert data(auto)["cart_editable"] is True
