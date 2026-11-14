"""Past Orders search over GET /api/orders: `q` and `line_names` (asked by person 1's PR #168).

`q` is a trimmed, case-insensitive substring over the row title, the standing order's title, the
order id, the proposal id, the destination, the delivery date, the line names and the product
ids. `line_names` lists at most five product names per row, biggest line total first. One query
serves the page whatever its size. Fixture catalogue and invented prices; every order is a mock.
"""

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_http import login
from test_orders_list import authorization

from aimo import orders_list
from aimo.api import create_app
from aimo.db import Problem, connection, js
from aimo.schemas import CommitRequest, PrepareRequest

SIX = [
    ("464306", "10", "L"),
    ("464398", "50", "L"),
    ("463380", "30", "L"),
    ("460123", "2", "KI"),
    ("460675", "10", "KG"),
    ("460035", "6", "KG"),
]


@pytest.fixture
def prepare(service, agent, request_data):
    def make(
        request_id="Hotel breakfast", lines=(("464306", "10", "L"),), destination=None, days=2
    ):
        body = request_data | {
            "request_id": request_id,
            "requirements": {},
            "idempotency_key": str(uuid4()),
            "delivery_date": str(date.today() + timedelta(days=days)),
            "lines": [{"product_id": p, "amount": a, "unit": u} for p, a, u in lines],
        }
        if destination:
            body["destination"] = destination
        return service.prepare_order(agent, PrepareRequest(**body))

    return make


@pytest.fixture
def place(service, buyer):
    def commit(p):
        body = CommitRequest(
            proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
        )
        return service.commit_order(buyer, body)

    return commit


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


def page(identity, query=None, **kw):
    return orders_list.orders_page(
        identity, kw.pop("offset", 0), kw.pop("limit", 20), query=query, **kw
    )


def ids(result):
    return [i["proposal_id"] or i["schedule_id"] for i in result["items"]]


def names_of(p):
    lines = sorted(p["snapshot"]["lines"], key=lambda line: -Decimal(line["gross"] or "0"))
    return [line["name"] for line in lines]


# --- line_names ------------------------------------------------------------------------------


def test_line_names_are_the_biggest_lines_first_and_at_most_five(buyer, prepare):
    p = prepare(lines=SIX)
    assert len(p["snapshot"]["lines"]) == 6
    item = page(buyer)["items"][0]
    assert item["line_names"] == names_of(p)[:5] and len(item["line_names"]) == 5


def test_a_one_line_request_lists_its_one_name(buyer, prepare):
    p = prepare()
    assert page(buyer)["items"][0]["line_names"] == names_of(p) == ["Demo Arki Eila milk drink 1 L"]


def test_a_scheduled_row_lists_the_agreed_line_names(buyer, prepare, place):
    source = place(prepare("Source"))
    authorization(
        buyer,
        source["order_id"],
        next_run=date.today() + timedelta(days=5),
        agreed_lines=[
            {"product_id": "464306", "name": "Alpha milk", "line_gross": "17.00"},
            {"product_id": "460123", "name": "Beta drink", "line_gross": "40.00"},
        ],
    )
    row = next(i for i in page(buyer)["items"] if i["status"] == "scheduled")
    assert row["line_names"] == ["Beta drink", "Alpha milk"]


# --- q ---------------------------------------------------------------------------------------


def test_q_matches_title_destination_delivery_date_and_names_case_insensitively(buyer, prepare):
    a = prepare("Wedding breakfast", lines=[("464306", "10", "L")], days=3)
    b = prepare("Staff lunch", lines=[("460675", "10", "KG")], days=5)
    when = str(date.today() + timedelta(days=3))
    assert ids(page(buyer, "wedding")) == [a["proposal_id"]]
    assert ids(page(buyer, "STAFF LUNCH")) == [b["proposal_id"]]
    assert ids(page(buyer, "hotel-helsinki")) and len(ids(page(buyer, "Hotel-Helsinki"))) == 2
    assert ids(page(buyer, when)) == [a["proposal_id"]]
    assert ids(page(buyer, "flank steak")) == [b["proposal_id"]]
    assert ids(page(buyer, "ARKI")) == [a["proposal_id"]]


def test_q_matches_product_ids_order_ids_and_proposal_ids(buyer, prepare, place):
    a = prepare("Placed one", lines=[("464306", "10", "L")])
    receipt = place(a)
    b = prepare("Pending one", lines=[("460675", "10", "KG")])
    assert ids(page(buyer, "460675")) == [b["proposal_id"]]
    assert ids(page(buyer, receipt["order_id"])) == [a["proposal_id"]]
    assert ids(page(buyer, b["proposal_id"][:13])) == [b["proposal_id"]]
    assert ids(page(buyer, receipt["order_id"].upper())) == [a["proposal_id"]]


def test_q_matches_the_standing_order_title_on_its_runs_and_on_the_scheduled_row(
    buyer, prepare, place
):
    source = place(prepare("Weekly dairy"))
    authorization(buyer, source["order_id"], next_run=date.today() + timedelta(days=5))
    other = prepare("Unrelated", lines=[("460035", "6", "KG")])
    hits = page(buyer, "weekly dairy")["items"]
    assert any(i["status"] == "scheduled" for i in hits)
    assert other["proposal_id"] not in ids(page(buyer, "weekly dairy"))


def test_q_is_trimmed_and_wildcards_are_literal(buyer, prepare):
    prepare("Plain order")
    assert len(page(buyer, "   plain  ")["items"]) == 1  # outer spaces are trimmed
    assert page(buyer, "plain  order")["items"] == []  # inner spaces are part of the text
    assert len(page(buyer, "  plain order  ")["items"]) == 1
    assert page(buyer, "%")["items"] == [] and page(buyer, "_")["items"] == []
    assert page(buyer, "p%n")["items"] == []


def test_q_without_a_match_gives_an_empty_page_with_a_zero_total(buyer, prepare):
    prepare()
    result = page(buyer, "no such thing")
    assert result == {"items": [], "next_offset": None, "total": 0}


def test_q_combines_with_the_status_filter_and_total_counts_every_match(buyer, prepare, place):
    for n in range(3):
        place(prepare(f"Milk run {n}"))
    prepare("Milk pending")
    prepare("Other thing", lines=[("460035", "6", "KG")])
    everything = page(buyer, "milk run")
    assert everything["total"] == 3 and len(everything["items"]) == 3
    first = page(buyer, "milk", limit=2)
    assert len(first["items"]) == 2 and first["total"] == 4 and first["next_offset"] == 2
    placed = page(buyer, "milk", statuses=["placed"])
    assert placed["total"] == 3 and {i["status"] for i in placed["items"]} == {"placed"}
    assert page(buyer, "milk", offset=10)["total"] == 4  # past the end still counts


def test_q_never_reaches_another_buyers_rows(buyer, prepare):
    prepare("Shared word")
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
    assert page(stranger, "shared word")["items"] == []
    assert len(page(buyer, "shared word")["items"]) == 1


def test_a_page_costs_the_same_number_of_statements_for_one_row_and_for_twenty(
    buyer, prepare, monkeypatch
):
    calls = []

    @contextmanager
    def counted():
        with connection() as c:

            class Counted:
                def execute(self, query, *args):
                    calls.append(query)
                    return c.execute(query, *args)

            yield Counted()

    monkeypatch.setattr(orders_list, "connection", counted)
    prepare("First")
    page(buyer, "first")
    one_row = len(calls)
    calls.clear()
    for n in range(19):
        prepare(f"Many {n}")
    calls.clear()
    result = page(buyer, "many", limit=20)
    assert len(result["items"]) == 19 and len(calls) == one_row


def test_q_longer_than_eighty_characters_after_trimming_is_refused(buyer):
    with pytest.raises(Problem) as error:
        page(buyer, "x" * 81)
    assert error.value.code == "INVALID_ORDER_QUERY" and error.value.status == 422
    assert page(buyer, "x" * 80)["items"] == []


# --- over HTTP -------------------------------------------------------------------------------


def test_http_q_and_line_names(http, prepare):
    a = prepare("Wedding breakfast", lines=SIX)
    prepare("Staff lunch", lines=[("460035", "6", "KG")])
    login(http)
    body = http.get("/api/orders?q=%20Wedding%20").json()
    assert [i["proposal_id"] for i in body["items"]] == [a["proposal_id"]] and body["total"] == 1
    assert body["items"][0]["line_names"] == names_of(a)[:5]
    assert http.get("/api/orders?q=").json()["total"] == 2  # empty means everything
    assert http.get("/api/orders?q=%20%20").json()["total"] == 2
    assert http.get("/api/orders?q=zzz").json() == {"items": [], "next_offset": None, "total": 0}


def test_http_q_longer_than_eighty_is_a_clear_422(http):
    login(http)
    response = http.get("/api/orders?q=" + "a" * 81)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ORDER_QUERY"


def test_http_q_needs_a_session(http):
    assert http.get("/api/orders?q=milk").status_code == 401


def test_openapi_declares_q_and_line_names(http):
    spec = http.app.openapi()
    params = {p["name"]: p for p in spec["paths"]["/api/orders"]["get"]["parameters"]}
    assert "q" in params and params["q"]["required"] is False
    item = spec["components"]["schemas"]["OrderListItem"]["properties"]
    assert item["line_names"]["type"] == "array" and item["line_names"]["maxItems"] == 5
