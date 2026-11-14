"""CNF-022/027/030/031/036/037 over HTTP: the customer's schedule routes.

Session cookie plus Origin and CSRF like the other write routes; buyer-scoped; Problem codes come
from `aimo.schedules`. Fixture supplier data; every order is a mock ("Accepted by demo order
service").
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_http import login

from aimo.api import create_app

WEEKLY = {"kind": "weekdays", "weekdays": [0, 1, 2, 3, 4, 5, 6], "every_weeks": 1}
FIRST = str(date.today() + timedelta(days=3))


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


def terms_of(http, headers, order):
    response = http.post(
        "/api/schedules/preview",
        headers=headers,
        json={"order_id": order["order_id"], "recurrence": WEEKLY, "first_run_date": FIRST},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create(http, headers, order, terms, **changes):
    body = {
        "order_id": order["order_id"],
        "recurrence": WEEKLY,
        "first_run_date": FIRST,
        "price_ceiling_gross": "100.00",
        "agreed_terms_fingerprint": terms["terms_fingerprint"],
        "idempotency_key": str(uuid4()),
    } | changes
    return http.post("/api/schedules", headers=headers, json=body)


@pytest.fixture
def made(http, placed_order):
    headers = login(http)
    terms = terms_of(http, headers, placed_order)
    schedule = create(http, headers, placed_order, terms)
    assert schedule.status_code == 200, schedule.text
    return headers, schedule.json(), terms


READS = [
    "/api/schedules",
    f"/api/schedules/{uuid4()}",
    "/api/schedules/substitute-candidates?product_id=464306",
]
WRITES = [
    "/api/schedules",
    "/api/schedules/preview",
    f"/api/schedules/{uuid4()}/preview",
    f"/api/schedules/{uuid4()}/replace",
    f"/api/schedules/{uuid4()}/cancel",
    f"/api/schedules/{uuid4()}/pause",
    f"/api/schedules/{uuid4()}/resume",
]


@pytest.mark.parametrize("url", READS)
def test_reads_need_a_session(http, url):
    assert http.get(url).status_code == 401


@pytest.mark.parametrize("url", WRITES)
def test_writes_need_a_session(http, url):
    assert http.post(url, json={}).status_code in (401, 403)
    assert http.post(url, json={}).status_code != 200


def valid_body(url):
    """A well-formed body, so that the refusal under test is the CSRF/Origin one, not a 422."""
    base = {"recurrence": WEEKLY, "first_run_date": FIRST}
    if url.endswith("/replace"):
        return base | {"agreed_terms_fingerprint": "0" * 64, "idempotency_key": "k" * 8}
    if url.endswith("/api/schedules") or url.endswith("/api/schedules/preview"):
        body = base | {"order_id": str(uuid4())}
        if url.endswith("/api/schedules"):
            body |= {
                "price_ceiling_gross": "100.00",
                "agreed_terms_fingerprint": "0" * 64,
                "idempotency_key": "k" * 8,
            }
        return body
    return {}


@pytest.mark.parametrize("url", WRITES)
def test_writes_need_csrf_and_a_same_origin(http, url):
    headers = login(http)
    body = valid_body(url)
    assert http.post(url, json=body).status_code == 403  # cookie only: no token, no origin
    wrong = headers | {"X-CSRF-Token": "wrong"}
    assert http.post(url, json=body, headers=wrong).status_code == 403
    foreign = headers | {"Origin": "https://evil.invalid"}
    assert http.post(url, json=body, headers=foreign).status_code == 403


def test_preview_then_create_then_list_and_get(http, placed_order):
    headers = login(http)
    terms = terms_of(http, headers, placed_order)
    assert terms["policy_outcome"] == "ready_to_commit" and len(terms["terms_fingerprint"]) == 64
    assert http.get("/api/schedules").json() == {"items": [], "next_offset": None}
    created = create(http, headers, placed_order, terms)
    assert created.status_code == 200
    schedule = created.json()
    assert (
        schedule["status"] == "active" and schedule["source_order_id"] == placed_order["order_id"]
    )
    listed = http.get("/api/schedules").json()
    assert [s["id"] for s in listed["items"]] == [schedule["id"]]
    detail = http.get(f"/api/schedules/{schedule['id']}").json()
    assert detail["id"] == schedule["id"] and detail["runs"] == []
    orders = http.get("/api/orders").json()["items"]
    scheduled = [o for o in orders if o["status"] == "scheduled"]
    assert [o["schedule_id"] for o in scheduled] == [schedule["id"]]
    assert scheduled[0]["scheduled_for"] == schedule["next_run_date"]


def test_creating_twice_with_one_key_returns_the_same_schedule(http, placed_order):
    headers = login(http)
    terms = terms_of(http, headers, placed_order)
    key = str(uuid4())
    first = create(http, headers, placed_order, terms, idempotency_key=key).json()
    again = create(http, headers, placed_order, terms, idempotency_key=key).json()
    assert again["id"] == first["id"]
    assert len(http.get("/api/schedules").json()["items"]) == 1


def test_a_stale_agreement_is_refused_with_the_documented_code(http, placed_order):
    headers = login(http)
    terms = terms_of(http, headers, placed_order)
    response = create(http, headers, placed_order, terms, agreed_terms_fingerprint="0" * 64)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCHEDULE_TERMS_CHANGED"


def test_a_ceiling_below_the_agreed_total_is_refused(http, placed_order):
    headers = login(http)
    terms = terms_of(http, headers, placed_order)
    response = create(http, headers, placed_order, terms, price_ceiling_gross="1.00")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCHEDULE_CEILING_TOO_LOW"


def test_cancel_stops_the_schedule_and_it_leaves_the_scheduled_orders(http, made):
    headers, schedule, _ = made
    response = http.post(f"/api/schedules/{schedule['id']}/cancel", headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    assert not [o for o in http.get("/api/orders").json()["items"] if o["status"] == "scheduled"]
    again = http.post(f"/api/schedules/{schedule['id']}/pause", headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "SCHEDULE_NOT_ACTIVE"


def test_pause_and_resume(http, made):
    headers, schedule, _ = made
    paused = http.post(f"/api/schedules/{schedule['id']}/pause", headers=headers)
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    listed = [o for o in http.get("/api/orders").json()["items"] if o["status"] == "scheduled"]
    assert listed[0]["paused"] is True
    resumed = http.post(f"/api/schedules/{schedule['id']}/resume", headers=headers)
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"


def test_edit_preview_then_replace_supersedes_the_old_schedule(http, made):
    headers, schedule, _ = made
    preview = http.post(
        f"/api/schedules/{schedule['id']}/preview",
        headers=headers,
        json={"recurrence": {"kind": "days", "interval": 4}},
    )
    assert preview.status_code == 200, preview.text
    replaced = http.post(
        f"/api/schedules/{schedule['id']}/replace",
        headers=headers,
        json={
            "recurrence": {"kind": "days", "interval": 4},
            "price_ceiling_gross": "100.00",
            "agreed_terms_fingerprint": preview.json()["terms_fingerprint"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert replaced.status_code == 200, replaced.text
    new = replaced.json()
    assert new["id"] != schedule["id"] and new["supersedes_id"] == schedule["id"]
    old = http.get(f"/api/schedules/{schedule['id']}").json()
    assert old["status"] == "superseded" and old["replaced_by"] == new["id"]


def test_substitute_candidates_is_not_parsed_as_a_schedule_id(http):
    login(http)
    response = http.get("/api/schedules/substitute-candidates?product_id=464306")
    assert response.status_code == 200, response.text
    assert response.json()["product_id"] == "464306"
    assert isinstance(response.json()["candidates"], list)


def test_unknown_and_malformed_ids(http):
    login(http)
    assert http.get(f"/api/schedules/{uuid4()}").status_code == 404
    assert http.get("/api/schedules/not-a-uuid").status_code == 422


def test_paging_parameters_are_bounded(http):
    login(http)
    assert http.get("/api/schedules?limit=0").status_code == 422
    assert http.get("/api/schedules?limit=51").status_code == 422
    assert http.get("/api/schedules?offset=-1").status_code == 422


def test_openapi_declares_every_schedule_route_and_model(http):
    spec = http.app.openapi()
    paths = spec["paths"]
    assert set(paths["/api/schedules"]) == {"get", "post"}
    for suffix in ("preview", "replace", "cancel", "pause", "resume"):
        assert "post" in paths[f"/api/schedules/{{schedule_id}}/{suffix}"]
    assert "post" in paths["/api/schedules/preview"]
    assert "get" in paths["/api/schedules/{schedule_id}"]
    assert "get" in paths["/api/schedules/substitute-candidates"]
    names = set(spec["components"]["schemas"])
    assert {"ScheduleResponse", "ScheduleDetail", "ScheduleList", "ScheduleTerms"} <= names
    assert {"ScheduleCreateRequest", "ScheduleReplaceRequest", "SubstituteCandidates"} <= names
