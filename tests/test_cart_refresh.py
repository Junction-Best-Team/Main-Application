# ruff: noqa: F811
"""Q-134 c: refresh an EXPIRED basket from the customer's current cart: POST /api/conversations/{id}/refresh-basket.

It prepares the cart again with fresh supplier price and stock, for the same delivery date and
destination, with exactly the pack counts the customer set (the stored cart is the source). It
authorizes and orders nothing: the customer still confirms the new revision. Only a basket whose
status is expired can be refreshed.
"""

import time
from decimal import Decimal
from uuid import uuid4

from test_cart_auto_prepare import auto, baskets, data, state  # noqa: F401
from test_cart_edit import lines_of, put, start  # noqa: F401
from test_draft_cart_purchase import (  # noqa: F401
    CUSTOMER_PLAN_TURN,
    call,
    chat,
    plan,
    say,
    tool_reply,
)

from aimo.config import settings


def expire(chat, monkeypatch, make):
    """`make()` prepares a basket that lives one second; after it, the normal 15 minutes apply."""
    ttl = settings().proposal_ttl_seconds
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", 1)
    made = make()
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", ttl)
    time.sleep(1.2)
    return made


def refresh(chat, cid=None, key=None, headers=True):
    return chat.client.post(
        f"/api/conversations/{cid or chat.turn.cid}/refresh-basket",
        headers=chat.headers if headers else {},
        json={"request_id": key or str(uuid4())},
    )


def test_an_expired_basket_is_prepared_again_with_the_customers_amounts_and_fresh_prices(
    auto, monkeypatch
):
    start(auto)
    edited = expire(
        auto, monkeypatch, lambda: put(auto, [("pepper", 3), ("pasta", 7)]).json()["proposal"]
    )
    assert data(auto)["purchases"][-1]["approval_status"] == "expired"
    auto.service.connector.price_multiplier = Decimal(2)  # the supplier's price moved meanwhile

    sent = refresh(auto)
    assert sent.status_code == 200, sent.text
    out = sent.json()["proposal"]
    assert out["proposal_id"] != edited["proposal_id"]
    assert out["approval_status"] != "expired" and out["order_id"] is None
    assert lines_of(out) == lines_of(edited)  # the customer's pack counts, unchanged
    assert out["request"]["delivery_date"] == edited["request"]["delivery_date"]
    assert out["request"]["destination"] == edited["request"]["destination"]
    assert Decimal(out["snapshot"]["gross_total"]) > Decimal(edited["snapshot"]["gross_total"])
    d = data(auto)
    open_now = [b for b in baskets(d) if state(b) != "cancelled"]
    assert [b["proposal_id"] for b in open_now] == [out["proposal_id"]]
    assert d["messages"][-1]["proposal_id"] == out["proposal_id"]


def test_a_basket_that_is_not_expired_is_not_refreshed(auto):
    first = start(auto)
    sent = refresh(auto)
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "BASKET_NOT_EXPIRED"
    assert [b["proposal_id"] for b in baskets(data(auto))] == [first["proposal_id"]]


def test_a_conversation_without_a_basket_has_nothing_to_refresh(auto):
    sent = refresh(auto, auto.new_conversation().cid)
    assert sent.status_code == 422 and sent.json()["error"]["code"] == "NO_BASKET_TO_REFRESH"


def test_a_retried_refresh_gives_the_same_basket(auto, monkeypatch):
    expire(auto, monkeypatch, lambda: start(auto))
    key = str(uuid4())
    first = refresh(auto, key=key)
    again = refresh(auto, key=key)
    assert first.status_code == again.status_code == 200
    assert again.json()["proposal"]["proposal_id"] == first.json()["proposal"]["proposal_id"]
    assert len(baskets(data(auto))) == 2


def test_a_refresh_needs_the_customers_csrf_session(auto, monkeypatch):
    expire(auto, monkeypatch, lambda: start(auto))
    assert refresh(auto, headers=False).status_code in (401, 403)
    assert len(baskets(data(auto))) == 1
