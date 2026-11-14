"""CNF-034 / Q-77 / Q-78: the customer's orders list, derived, never an update of an order.

Each row has one status: `scheduled` (an active standing order, with its next run date),
`pending` (a request being processed and placed), `placed` (a mock order), `cancelled`. Expired
unconfirmed requests and requests replaced by a retry are hidden. Fixture catalog and invented
prices only; every order is a mock ("Accepted by demo order service").
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from aimo import cancellations, orders_list
from aimo.db import connection, js
from aimo.schemas import CommitRequest, PrepareRequest

NOW = datetime.now(timezone.utc)


def commit_request(p):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )


@pytest.fixture
def prepare(service, agent, request_data):
    def make(request_id="Hotel breakfast", amount="10"):
        body = request_data | {
            "request_id": request_id,
            "idempotency_key": str(uuid4()),
            "lines": [{"product_id": "464306", "amount": amount, "unit": "L"}],
        }
        return service.prepare_order(agent, PrepareRequest(**body))

    return make


@pytest.fixture
def place(service, buyer):
    return lambda p: service.commit_order(buyer, commit_request(p))


def authorization(buyer, order_id, *, next_run=None, status="active"):
    """Insert a standing authorization the way schedules.create stores it (authored row)."""
    aid = uuid4()
    first = date.today() + timedelta(days=2)
    with connection() as c:
        c.execute(
            """INSERT INTO scheduled_authorizations(id,buyer_id,created_by,source_order_id,
            create_key,create_hash,request,agreed_lines,terms_fingerprint,currency,
            agreed_gross_total,price_ceiling_gross,delivery_offset_days,recurrence,first_run_date,
            valid_until,status,stop_reason,next_run_date,paused_at)
            VALUES(%s,%s,%s,%s,%s,'h',%s,'[]','fp','EUR',17,20,2,%s,%s,%s,%s,%s,%s,%s)""",
            (
                aid,
                buyer["buyer_id"],
                buyer["id"],
                order_id,
                str(aid),
                js({"destination": "hotel-helsinki", "lines": [{"product_id": "464306"}]}),
                js({"kind": "days", "interval": 7}),
                first,
                first + timedelta(days=300),
                status,
                "test" if status == "stopped" else None,
                next_run if status in ("active", "paused") else None,
                NOW if status == "paused" else None,
            ),
        )
    return str(aid)


def scheduled_run(aid, buyer, proposal_id, day=None):
    """A run of the authorization that produced this proposal (authored row)."""
    day = day or date.today()
    with connection() as c:
        c.execute(
            """INSERT INTO scheduled_runs(id,authorization_id,buyer_id,scheduled_date,delivery_date,
            status,proposal_id) VALUES(%s,%s,%s,%s,%s,'prepared',%s)""",
            (uuid4(), aid, buyer["buyer_id"], day, day + timedelta(days=1), proposal_id),
        )


def page(identity, offset=0, limit=20, now=None):
    return orders_list.orders_page(identity, offset, limit, now=now)


def by_status(result):
    out = {}
    for item in result["items"]:
        out.setdefault(item["status"], []).append(item)
    return out


def test_a_prepared_request_is_pending(buyer, prepare):
    p = prepare()
    item = page(buyer)["items"][0]
    assert item["status"] == "pending" and item["proposal_id"] == p["proposal_id"]
    assert item["order_id"] is None and item["schedule_id"] is None
    assert item["title"] == "Hotel breakfast" and item["currency"] == "EUR"
    assert item["gross_total"] == p["snapshot"]["gross_total"]
    assert item["line_count"] == 1 and item["scheduled_for"] is None


def test_a_committed_order_is_placed_with_its_order_id(buyer, prepare, place):
    p = prepare()
    receipt = place(p)
    item = page(buyer)["items"][0]
    assert item["status"] == "placed" and item["order_id"] == receipt["order_id"]
    assert item["proposal_id"] == p["proposal_id"]
    assert len(page(buyer)["items"]) == 1  # one row for the request, not a second for the order


def test_a_customer_cancelled_request_is_cancelled_with_its_reason(buyer, prepare):
    p = prepare()
    cancellations.cancel_my_request(buyer, p["proposal_id"])
    item = page(buyer)["items"][0]
    assert item["status"] == "cancelled" and item["cancel_reason"] == "customer_cancelled"


def test_a_request_replaced_by_a_retry_is_hidden(buyer, prepare):
    p = prepare()
    with connection() as c:
        cancellations.cancel_request(
            c,
            proposal_id=p["proposal_id"],
            buyer_id=buyer["buyer_id"],
            reason="run_retry",
            by=buyer["id"],
        )
    assert page(buyer)["items"] == []


def test_a_disrupted_run_request_shows_as_cancelled(buyer, prepare):
    p = prepare()
    with connection() as c:
        cancellations.cancel_request(
            c,
            proposal_id=p["proposal_id"],
            buyer_id=buyer["buyer_id"],
            reason="run_disrupted",
            by=buyer["id"],
        )
    assert page(buyer)["items"][0]["cancel_reason"] == "run_disrupted"


def test_an_expired_unconfirmed_request_is_hidden_but_a_placed_one_never_is(buyer, prepare, place):
    expiring = prepare("Expires")
    placed = prepare("Placed")
    place(placed)
    later = NOW + timedelta(days=3)  # past every proposal's expiry
    shown = page(buyer, now=later)["items"]
    assert [i["proposal_id"] for i in shown] == [placed["proposal_id"]]
    assert expiring["proposal_id"] not in [i["proposal_id"] for i in shown]
    assert len(page(buyer, now=NOW)["items"]) == 2


def test_a_cancelled_expired_request_is_still_listed_as_cancelled(buyer, prepare):
    p = prepare()
    cancellations.cancel_my_request(buyer, p["proposal_id"])
    item = page(buyer, now=NOW + timedelta(days=3))["items"][0]
    assert item["status"] == "cancelled"


def test_an_active_authorization_is_scheduled_with_its_next_run_date(buyer, prepare, place):
    order = place(prepare("Source"))
    soon = date.today() + timedelta(days=3)
    aid = authorization(buyer, order["order_id"], next_run=soon)
    scheduled = by_status(page(buyer))["scheduled"]
    assert len(scheduled) == 1
    row = scheduled[0]
    assert row["schedule_id"] == aid and row["scheduled_for"] == soon.isoformat()
    assert row["proposal_id"] is None and row["order_id"] is None
    # The label is the source order's request label, like ScheduleResponse.title.
    assert row["title"] == "Source" and row["schedule_title"] == "Source"
    assert row["gross_total"] == "17.00" and row["paused"] is False and row["line_count"] == 1


def test_a_paused_authorization_is_scheduled_and_marked_paused(buyer, prepare, place):
    order = place(prepare("Source"))
    soon = date.today() + timedelta(days=4)
    aid = authorization(buyer, order["order_id"], next_run=soon, status="paused")
    row = by_status(page(buyer))["scheduled"][0]
    assert row["schedule_id"] == aid and row["paused"] is True
    assert row["scheduled_for"] == soon.isoformat() and row["order_id"] is None


def test_requests_of_a_run_carry_the_schedule_and_ordinary_ones_do_not(buyer, prepare, place):
    source = place(prepare("Source"))
    aid = authorization(buyer, source["order_id"], next_run=date.today() + timedelta(days=7))
    from_run = prepare("Run request")
    place(from_run)
    waiting = prepare("Run waiting")
    scheduled_run(aid, buyer, from_run["proposal_id"])
    scheduled_run(aid, buyer, waiting["proposal_id"], day=date.today() + timedelta(days=1))
    ordinary = prepare("Ordinary")
    rows = {i["proposal_id"]: i for i in page(buyer)["items"] if i["proposal_id"]}
    for p in (from_run, waiting):
        assert rows[p["proposal_id"]]["schedule_id"] == aid
        assert rows[p["proposal_id"]]["schedule_title"] == "Source"
    assert rows[from_run["proposal_id"]]["status"] == "placed"
    assert rows[waiting["proposal_id"]]["status"] == "pending"
    assert rows[ordinary["proposal_id"]]["schedule_id"] is None
    assert rows[ordinary["proposal_id"]]["schedule_title"] is None
    assert rows[ordinary["proposal_id"]]["paused"] is False
    assert len(rows) == 4  # one row per request even with a run attached


@pytest.mark.parametrize("status", ["stopped", "cancelled", "expired", "superseded"])
def test_a_finished_authorization_is_not_listed_as_scheduled(buyer, prepare, place, status):
    order = place(prepare("Source"))
    authorization(buyer, order["order_id"], status=status)
    assert "scheduled" not in by_status(page(buyer))


def test_the_list_is_newest_first_and_pages_without_gaps_or_repeats(buyer, prepare):
    made = [prepare(f"Order {n}")["proposal_id"] for n in range(5)]
    first = page(buyer, 0, 2)
    second = page(buyer, first["next_offset"], 2)
    third = page(buyer, second["next_offset"], 2)
    ids = [i["proposal_id"] for r in (first, second, third) for i in r["items"]]
    assert ids == list(reversed(made))
    assert first["next_offset"] == 2 and second["next_offset"] == 4
    assert third["next_offset"] is None


def test_only_the_callers_own_buyer_is_listed(buyer, prepare):
    prepare("Mine")
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other-hotel','456',1) ON CONFLICT DO NOTHING")
        rules = c.execute(
            "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
        ).fetchone()["rules"]
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('other-hotel',1,%s) "
            "ON CONFLICT DO NOTHING",
            (js(rules),),
        )
        c.execute(
            """INSERT INTO identities VALUES('other-approver','other-hotel','approver',true,'!x',
            '{"currency":"EUR","max_gross":"5000.00","exceptions":[]}') ON CONFLICT DO NOTHING"""
        )
        stranger = c.execute("SELECT * FROM identities WHERE id='other-approver'").fetchone()
    assert page(stranger)["items"] == []
    assert len(page(buyer)["items"]) == 1


def test_listing_writes_nothing_and_leaves_orders_untouched(buyer, prepare, place):
    place(prepare())
    with connection() as c:
        before = c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]
    page(buyer)
    page(buyer)
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == before
        assert (
            c.execute("SELECT count(*) AS n FROM order_request_cancellations").fetchone()["n"] == 0
        )


def test_a_scheduler_or_agent_identity_gets_forbidden(agent):
    from aimo.db import Problem

    with pytest.raises(Problem) as error:
        page(agent)
    assert error.value.code == "FORBIDDEN" and error.value.status == 403
