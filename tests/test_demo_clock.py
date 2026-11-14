"""JNP3-FUL-001..005 and JNP3-CLK-001..006: the simulated fulfilment status and the demo clock.

THESE TESTS ARE THE SPEC and are written before the code (branch p3/flow-tests). Until `aimo.clock`
exists they fail on purpose. The contract, one place (owner answers Q-110 to Q-121, 2026-11-14):

* Fulfilment is DERIVED, never stored (`orders` is append-only). With D = the order's delivery date
  (Europe/Helsinki) and t = the clock: `accepted` while t < D-1 00:00; `preparing` from D-1 00:00;
  `out_for_delivery` from D 06:00; `delivered` from D 12:00 (final). Same-day delivery skips the
  states already passed. `order_status` stays `accepted_mock`.
* `aimo.clock` (new module). All real-time reads of this module go through `clock.real_now()`
  (tests pin it). `clock.app_now(buyer_id)` = `real_now()` + that buyer's offset, but only while
  `settings().demo_clock_enabled` is on and the supplier mode is not live; otherwise it is real.
  `aimo.db.now()` is NOT changed by a jump.
* Settings: `demo_clock_enabled: bool = False` (env DEMO_CLOCK_ENABLED).
* Tables (migration 025_demo_clock.sql): `demo_clock(buyer_id PK, offset_seconds, updated_at)` and
  append-only `demo_clock_events(id, buyer_id, actor_id, kind, jump_days, jump_to, old_offset_seconds,
  new_offset_seconds, real_at, created_at)`; UPDATE and DELETE are refused ("immutable history").
* Routes (customer session; POST also needs CSRF and Origin; answer 404 when the clock is disabled
  or the supplier mode is live): GET /api/demo/clock, POST /api/demo/clock/advance,
  POST /api/demo/clock/reset.
* Responses carry `fulfilment` {status, since, next_status, next_at, simulated: true, clock}; `clock`
  is "demo" while the buyer's offset is above zero and the clock is enabled, otherwise "real".
* `GET /api/purchases/{id}` (`ProposalResponse`), the receipt (`OrderResponse`, which also gains
  `delivery_date` and `destination`) and `placed` rows of `GET /api/orders` carry `fulfilment`;
  it is null while there is no order. Advance body: exactly one of `days` (1..30) or
  `to: "delivery_day"` (06:00 Helsinki on the delivery date of the buyer's earliest undelivered
  order, forward only, within 30 days), plus `idempotency_key`. Error codes: 409 DEMO_CLOCK_LIMIT
  (over 400 days in total), 409 NO_PENDING_DELIVERY, 409 DEMO_CLOCK_NOT_FORWARD, 409
  IDEMPOTENCY_CONFLICT; a bad jump size is 422. `clock` reads the supplier mode through
  `upstream.effective_mode()` (looked up at call time).

Every order and every supplier fact here is a mock (fixture supplier). Nothing calls the live API.
"""

from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from wsc_support import OTHER_APPROVER, OTHER_PASSWORD, add_second_buyer, login_headers

from aimo import auth, conversations, scheduler
from aimo import db as aimo_db
from aimo.api import create_app
from aimo.config import settings
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, PrepareRequest
from aimo.upstream import HELSINKI

UTC = timezone.utc
BUYER = "demo-hotel"
ACTOR = "buyer"
FAR_DAYS = (
    40  # more than one jump (30 days); the fixture supplier allows it (see the probe in the PR)
)
FULFILMENT_KEYS = {"status", "since", "next_status", "next_at", "simulated", "clock"}


def key():
    return str(uuid4())


def helsinki(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=HELSINKI)


@pytest.fixture
def clock():
    """The module under test, imported lazily so each test fails by itself while it is missing."""
    return import_module("aimo.clock")


@pytest.fixture(autouse=True)
def clean_clock_tables():
    def wipe():
        with connection() as c:
            c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
            c.execute("TRUNCATE demo_clock, demo_clock_events")

    try:
        wipe()
    except psycopg.errors.UndefinedTable:
        pass  # the migration is not written yet; the tests below fail on their own
    yield
    try:
        wipe()
    except psycopg.errors.UndefinedTable:
        pass


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings(), "demo_clock_enabled", True)


@pytest.fixture
def pinned(clock, monkeypatch):
    """Real time fixed at 08:00 Helsinki today, so every expectation is exact."""
    today = scheduler.helsinki_today()
    instant = helsinki(today.year, today.month, today.day, 8)
    monkeypatch.setattr(clock, "real_now", lambda: instant)
    return instant


@pytest.fixture
def http(service):
    with TestClient(create_app(service)) as client:
        yield client


@pytest.fixture
def csrf(http):
    return login_headers(http)


def place(service, identity, request_data, days_ahead=2, **overrides):
    """A confirmed mock order for `identity`'s buyer delivering `days_ahead` Helsinki days from today."""
    data = dict(request_data, idempotency_key=key())
    data["delivery_date"] = str(scheduler.helsinki_today() + timedelta(days=days_ahead))
    data.update(overrides)
    p = service.prepare_order(auth.internal_agent(identity), PrepareRequest.model_validate(data))
    body = CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=key())
    receipt = conversations.confirm(identity, p["proposal_id"], body, service)
    return p["proposal_id"], receipt, date.fromisoformat(data["delivery_date"])


# --- JNP3-FUL-001: the derived status, all thresholds ---------------------------------------------

D = date(2026, 11, 17)  # winter time, UTC+2


@pytest.mark.parametrize(
    "now, status",
    [
        (helsinki(2026, 11, 15, 23, 59, 59), "accepted"),
        (helsinki(2026, 11, 16, 0, 0, 0), "preparing"),  # D-1 00:00
        (helsinki(2026, 11, 17, 5, 59, 59), "preparing"),
        (helsinki(2026, 11, 17, 6, 0, 0), "out_for_delivery"),  # D 06:00
        (helsinki(2026, 11, 17, 11, 59, 59), "out_for_delivery"),
        (helsinki(2026, 11, 17, 12, 0, 0), "delivered"),  # D 12:00
        (helsinki(2026, 11, 17, 23, 59, 59), "delivered"),
        (helsinki(2027, 3, 1, 12), "delivered"),
        (helsinki(2026, 11, 1, 12), "accepted"),
    ],
)
def test_the_four_states_switch_exactly_at_the_thresholds(clock, now, status):
    assert clock.fulfilment(D, now)["status"] == status


def test_the_result_shape_and_the_simulated_label(clock):
    result = clock.fulfilment(D, helsinki(2026, 11, 16, 9))
    assert set(result) == FULFILMENT_KEYS
    assert result["status"] == "preparing" and result["simulated"] is True
    assert result["clock"] == "real"
    assert result["since"] == helsinki(2026, 11, 16, 0)  # when this state began
    assert result["next_status"] == "out_for_delivery"
    assert result["next_at"] == helsinki(2026, 11, 17, 6)


def test_next_status_and_next_at_for_every_state(clock):
    accepted = clock.fulfilment(D, helsinki(2026, 11, 10, 9))
    assert (accepted["next_status"], accepted["next_at"]) == ("preparing", helsinki(2026, 11, 16))
    assert accepted["since"] is None  # no accept time is known to the pure function
    when = datetime(2026, 11, 10, 7, 0, tzinfo=UTC)
    assert clock.fulfilment(D, helsinki(2026, 11, 10, 9), accepted_at=when)["since"] == when
    out = clock.fulfilment(D, helsinki(2026, 11, 17, 7))
    assert (out["next_status"], out["next_at"]) == ("delivered", helsinki(2026, 11, 17, 12))
    assert out["since"] == helsinki(2026, 11, 17, 6)
    done = clock.fulfilment(D, helsinki(2026, 11, 17, 12))
    assert done["status"] == "delivered" and done["since"] == helsinki(2026, 11, 17, 12)
    assert done["next_status"] is None and done["next_at"] is None  # delivered is final


def test_the_clock_label_is_passed_through(clock):
    assert clock.fulfilment(D, helsinki(2026, 11, 16, 9), clock="demo")["clock"] == "demo"


def test_a_naive_time_is_refused(clock):
    with pytest.raises(ValueError):
        clock.fulfilment(D, datetime(2026, 11, 16, 9))


# --- The Helsinki date boundary, across both daylight-saving changes ------------------------------


def utc(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=UTC)


def test_the_boundary_follows_the_helsinki_date_not_the_utc_date(clock):
    # 22:00 UTC on 15 Nov is already 16 Nov in Helsinki (UTC+2): D-1 00:00.
    assert clock.fulfilment(D, utc(2026, 11, 15, 21, 59, 59))["status"] == "accepted"
    assert clock.fulfilment(D, utc(2026, 11, 15, 22, 0, 0))["status"] == "preparing"
    assert clock.fulfilment(D, utc(2026, 11, 17, 3, 59, 59))["status"] == "preparing"  # 05:59:59
    assert clock.fulfilment(D, utc(2026, 11, 17, 4, 0, 0))["status"] == "out_for_delivery"
    assert clock.fulfilment(D, utc(2026, 11, 17, 9, 59, 59))["status"] == "out_for_delivery"
    assert clock.fulfilment(D, utc(2026, 11, 17, 10, 0, 0))["status"] == "delivered"


def test_the_clock_change_in_autumn(clock):
    d = date(2026, 10, 25)  # 25 Oct 2026: 04:00 EEST (UTC+3) becomes 03:00 EET (UTC+2)
    assert clock.fulfilment(d, utc(2026, 10, 23, 20, 59, 59))["status"] == "accepted"
    assert (
        clock.fulfilment(d, utc(2026, 10, 23, 21, 0, 0))["status"] == "preparing"
    )  # 24 Oct 00:00 EEST
    assert clock.fulfilment(d, utc(2026, 10, 25, 3, 59, 59))["status"] == "preparing"
    assert (
        clock.fulfilment(d, utc(2026, 10, 25, 4, 0, 0))["status"] == "out_for_delivery"
    )  # 06:00 EET
    assert clock.fulfilment(d, utc(2026, 10, 25, 9, 59, 59))["status"] == "out_for_delivery"
    assert clock.fulfilment(d, utc(2026, 10, 25, 10, 0, 0))["status"] == "delivered"  # 12:00 EET


def test_the_clock_change_in_spring(clock):
    d = date(2027, 3, 28)  # 28 Mar 2027: 03:00 EET (UTC+2) becomes 04:00 EEST (UTC+3)
    assert clock.fulfilment(d, utc(2027, 3, 26, 21, 59, 59))["status"] == "accepted"
    assert (
        clock.fulfilment(d, utc(2027, 3, 26, 22, 0, 0))["status"] == "preparing"
    )  # 27 Mar 00:00 EET
    assert clock.fulfilment(d, utc(2027, 3, 28, 2, 59, 59))["status"] == "preparing"
    assert (
        clock.fulfilment(d, utc(2027, 3, 28, 3, 0, 0))["status"] == "out_for_delivery"
    )  # 06:00 EEST
    assert clock.fulfilment(d, utc(2027, 3, 28, 8, 59, 59))["status"] == "out_for_delivery"
    assert clock.fulfilment(d, utc(2027, 3, 28, 9, 0, 0))["status"] == "delivered"  # 12:00 EEST


# --- Same-day and past deliveries -----------------------------------------------------------------


def test_same_day_delivery_skips_the_states_already_passed(clock):
    day = date(2026, 11, 17)
    assert clock.fulfilment(day, helsinki(2026, 11, 17, 5))["status"] == "preparing"
    assert clock.fulfilment(day, helsinki(2026, 11, 17, 7))["status"] == "out_for_delivery"
    assert clock.fulfilment(day, helsinki(2026, 11, 17, 13))["status"] == "delivered"


def test_next_day_delivery_ordered_the_evening_before_is_already_preparing(clock):
    assert clock.fulfilment(D, helsinki(2026, 11, 16, 20))["status"] == "preparing"


def test_a_delivery_date_in_the_past_is_delivered(clock):
    assert clock.fulfilment(date(2025, 1, 1), helsinki(2026, 11, 16, 9))["status"] == "delivered"


# --- JNP3-CLK-001/002: off by default, refused with the live supplier ----------------------------


def test_the_clock_is_off_by_default():
    assert settings().demo_clock_enabled is False


def test_when_disabled_the_clock_is_real_even_if_an_offset_row_exists(clock, pinned):
    with connection() as c:
        c.execute(
            "INSERT INTO demo_clock(buyer_id,offset_seconds,updated_at) VALUES(%s,%s,now())",
            (BUYER, 5 * 86400),
        )
    assert settings().demo_clock_enabled is False
    assert clock.app_now(BUYER) == pinned


def test_disabled_routes_answer_404_and_write_nothing(http, csrf):
    assert http.get("/api/demo/clock").status_code == 404
    advance = http.post(
        "/api/demo/clock/advance", headers=csrf, json={"days": 1, "idempotency_key": key()}
    )
    assert advance.status_code == 404 and advance.json()["error"]["code"]
    assert (
        http.post(
            "/api/demo/clock/reset", headers=csrf, json={"idempotency_key": key()}
        ).status_code
        == 404
    )
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM demo_clock_events").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "mode, api_key",
    [("live", "k"), ("live", ""), ("auto", "some-key")],  # `auto` with a key is live
)
def test_startup_refuses_the_demo_clock_with_the_live_supplier(monkeypatch, mode, api_key):
    from aimo import upstream

    monkeypatch.setattr(settings(), "demo_clock_enabled", True)
    monkeypatch.setattr(settings(), "upstream_mode", mode)
    monkeypatch.setattr(settings(), "valio_aimo_api_key", api_key)
    monkeypatch.setattr(settings(), "secure_cookies", False)  # local: only the clock rule applies
    with pytest.raises(RuntimeError, match="DEMO_CLOCK_ENABLED"):
        upstream.check_supplier_startup()


def test_the_api_does_not_start_with_the_clock_and_the_live_supplier(service, monkeypatch):
    monkeypatch.setattr(settings(), "demo_clock_enabled", True)
    monkeypatch.setattr(settings(), "upstream_mode", "live")
    monkeypatch.setattr(settings(), "valio_aimo_api_key", "k")
    monkeypatch.setattr(settings(), "secure_cookies", False)
    with pytest.raises(RuntimeError, match="DEMO_CLOCK_ENABLED"):
        with TestClient(create_app(service)):
            pass


def test_the_clock_is_allowed_with_fixture_mode_and_with_auto_without_a_key(monkeypatch):
    from aimo import upstream

    monkeypatch.setattr(settings(), "demo_clock_enabled", True)
    monkeypatch.setattr(settings(), "secure_cookies", False)
    monkeypatch.setattr(settings(), "upstream_mode", "fixture")
    upstream.check_supplier_startup()
    monkeypatch.setattr(settings(), "upstream_mode", "auto")
    monkeypatch.setattr(settings(), "valio_aimo_api_key", "")
    upstream.check_supplier_startup()


def test_a_live_supplier_at_run_time_also_turns_the_routes_off(http, csrf, enabled, monkeypatch):
    from aimo import upstream

    assert http.get("/api/demo/clock").status_code == 200
    monkeypatch.setattr(upstream, "effective_mode", lambda: "live")
    assert http.get("/api/demo/clock").status_code == 404
    assert (
        http.post(
            "/api/demo/clock/advance", headers=csrf, json={"days": 1, "idempotency_key": key()}
        ).status_code
        == 404
    )


def test_the_migration_creates_the_clock_tables(clock):
    with connection() as c:
        cols = lambda t: {  # noqa: E731
            r["column_name"]
            for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=%s", (t,)
            ).fetchall()
        }
        assert {"buyer_id", "offset_seconds", "updated_at"} <= cols("demo_clock")
        assert {
            "id",
            "buyer_id",
            "actor_id",
            "kind",
            "jump_days",
            "jump_to",
            "old_offset_seconds",
            "new_offset_seconds",
            "real_at",
            "created_at",
        } <= cols("demo_clock_events")


# --- JNP3-CLK-003/004/005/006: module-level behaviour --------------------------------------------


def test_app_now_is_real_time_plus_the_buyers_offset(clock, enabled, pinned):
    assert clock.app_now(BUYER) == pinned
    clock.advance(BUYER, ACTOR, days=3, idempotency_key=key())
    assert clock.app_now(BUYER) == pinned + timedelta(days=3)
    assert clock.app_now("someone-else") == pinned  # per buyer (JNP3-CLK-004)


def test_a_jump_does_not_move_the_database_clock(clock, enabled, pinned):
    clock.advance(BUYER, ACTOR, days=30, idempotency_key=key())
    assert abs(aimo_db.now() - datetime.now(UTC)) < timedelta(seconds=5)


def test_a_jump_is_audited_in_an_append_only_table(clock, enabled, pinned):
    clock.advance(BUYER, ACTOR, days=2, idempotency_key=key())
    clock.advance(BUYER, ACTOR, days=5, idempotency_key=key())
    clock.reset(BUYER, ACTOR, idempotency_key=key())
    with connection() as c:
        rows = c.execute("SELECT * FROM demo_clock_events ORDER BY created_at, id").fetchall()
    assert [r["kind"] for r in rows] == ["advance", "advance", "reset"]
    assert [(r["old_offset_seconds"], r["new_offset_seconds"]) for r in rows] == [
        (0, 2 * 86400),
        (2 * 86400, 7 * 86400),
        (7 * 86400, 0),
    ]
    assert [r["jump_days"] for r in rows] == [2, 5, None]
    assert {r["buyer_id"] for r in rows} == {BUYER} and {r["actor_id"] for r in rows} == {ACTOR}
    assert all(r["real_at"] == pinned for r in rows)  # the REAL time of the jump, not the demo time
    for statement in ("UPDATE demo_clock_events SET kind='reset'", "DELETE FROM demo_clock_events"):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
            with connection() as c:
                c.execute(statement)


def test_one_jump_is_at_most_30_days_and_forward_only(clock, enabled, pinned):
    for bad in (0, -1, 31, 365):
        with pytest.raises(Problem) as err:
            clock.advance(BUYER, ACTOR, days=bad, idempotency_key=key())
        assert err.value.status == 422
    assert clock.app_now(BUYER) == pinned
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM demo_clock_events").fetchone()["n"] == 0
    clock.advance(BUYER, ACTOR, days=30, idempotency_key=key())  # exactly the limit is allowed
    assert clock.app_now(BUYER) == pinned + timedelta(days=30)


def test_the_total_is_at_most_400_days_per_buyer_and_reset_gives_it_back(clock, enabled, pinned):
    for _ in range(13):
        clock.advance(BUYER, ACTOR, days=30, idempotency_key=key())  # 390
    clock.advance(BUYER, ACTOR, days=10, idempotency_key=key())  # exactly 400
    with pytest.raises(Problem) as err:
        clock.advance(BUYER, ACTOR, days=1, idempotency_key=key())
    assert err.value.status == 409 and err.value.code == "DEMO_CLOCK_LIMIT"
    assert clock.app_now(BUYER) == pinned + timedelta(days=400)  # the refusal changed nothing
    clock.reset(BUYER, ACTOR, idempotency_key=key())
    assert clock.app_now(BUYER) == pinned
    clock.advance(BUYER, ACTOR, days=30, idempotency_key=key())
    assert clock.app_now(BUYER) == pinned + timedelta(days=30)


def test_the_same_key_applies_a_jump_once(clock, enabled, pinned):
    k = key()
    first = clock.advance(BUYER, ACTOR, days=2, idempotency_key=k)
    again = clock.advance(BUYER, ACTOR, days=2, idempotency_key=k)
    assert first == again
    assert clock.app_now(BUYER) == pinned + timedelta(days=2)
    with pytest.raises(Problem) as err:  # the same key for a different jump
        clock.advance(BUYER, ACTOR, days=3, idempotency_key=k)
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM demo_clock_events").fetchone()["n"] == 1


def test_the_module_refuses_when_disabled(clock, pinned):
    with pytest.raises(Problem) as err:
        clock.advance(BUYER, ACTOR, days=1, idempotency_key=key())
    assert err.value.status == 404
    assert clock.app_now(BUYER) == pinned


# --- JNP3-CLK-001/003/005/006: the HTTP routes ---------------------------------------------------


def test_the_clock_state_route(http, csrf, enabled, pinned):
    body = http.get("/api/demo/clock").json()
    assert body == {
        "enabled": True,
        "real_now": body["real_now"],
        "demo_now": body["demo_now"],
        "offset_seconds": 0,
        "offset_days": 0,
        "max_jump_days": 30,
        "max_total_days": 400,
    }
    assert (
        datetime.fromisoformat(body["demo_now"])
        == pinned
        == datetime.fromisoformat(body["real_now"])
    )


def test_the_clock_routes_need_a_session_and_the_post_routes_need_csrf(http, csrf, enabled):
    with TestClient(create_app(http.app.state.service)) as anonymous:
        assert anonymous.get("/api/demo/clock").status_code == 401
        assert (
            anonymous.post(
                "/api/demo/clock/advance",
                headers={"Origin": "http://testserver"},
                json={"days": 1, "idempotency_key": key()},
            ).status_code
            == 401
        )
    no_token = {"Origin": csrf["Origin"]}
    wrong_origin = dict(csrf, Origin="https://evil.example")
    for headers in (no_token, wrong_origin):
        response = http.post(
            "/api/demo/clock/advance", headers=headers, json={"days": 1, "idempotency_key": key()}
        )
        assert response.status_code == 403, response.text
    assert http.get("/api/demo/clock").json()["offset_days"] == 0


def test_advance_and_reset_over_http(http, csrf, enabled, pinned):
    r = http.post(
        "/api/demo/clock/advance", headers=csrf, json={"days": 7, "idempotency_key": key()}
    )
    assert r.status_code == 200, r.text
    assert r.json()["offset_days"] == 7 and r.json()["offset_seconds"] == 7 * 86400
    assert datetime.fromisoformat(r.json()["demo_now"]) == pinned + timedelta(days=7)
    assert http.get("/api/demo/clock").json()["offset_days"] == 7
    r = http.post("/api/demo/clock/reset", headers=csrf, json={"idempotency_key": key()})
    assert r.status_code == 200 and r.json()["offset_days"] == 0
    assert datetime.fromisoformat(r.json()["demo_now"]) == pinned


def test_a_bad_jump_over_http_is_a_422_envelope_and_changes_nothing(http, csrf, enabled, pinned):
    for body in (
        {"days": 31},
        {"days": 0},
        {"days": -3},
        {"days": 1.5},
        {"days": 1, "to": "delivery_day"},  # exactly one of the two
        {"to": "tomorrow"},
        {},
    ):
        r = http.post(
            "/api/demo/clock/advance", headers=csrf, json=dict(body, idempotency_key=key())
        )
        assert r.status_code == 422, (body, r.text)
        assert set(r.json()) == {"error"} and r.json()["error"]["code"]
    assert http.get("/api/demo/clock").json()["offset_days"] == 0


def test_the_total_limit_over_http(http, csrf, enabled, pinned):
    for _ in range(13):
        assert (
            http.post(
                "/api/demo/clock/advance", headers=csrf, json={"days": 30, "idempotency_key": key()}
            ).status_code
            == 200
        )
    assert (
        http.post(
            "/api/demo/clock/advance", headers=csrf, json={"days": 10, "idempotency_key": key()}
        ).status_code
        == 200
    )
    r = http.post(
        "/api/demo/clock/advance", headers=csrf, json={"days": 1, "idempotency_key": key()}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEMO_CLOCK_LIMIT"
    assert http.get("/api/demo/clock").json()["offset_days"] == 400


def test_to_delivery_day_goes_to_06_00_on_the_next_undelivered_orders_delivery_date(
    http, csrf, enabled, pinned, service, buyer, request_data
):
    r = http.post(
        "/api/demo/clock/advance",
        headers=csrf,
        json={"to": "delivery_day", "idempotency_key": key()},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_PENDING_DELIVERY"
    proposal_id, _, delivery = place(service, buyer, request_data, days_ahead=2)
    r = http.post(
        "/api/demo/clock/advance",
        headers=csrf,
        json={"to": "delivery_day", "idempotency_key": key()},
    )
    assert r.status_code == 200, r.text
    assert datetime.fromisoformat(r.json()["demo_now"]) == helsinki(
        delivery.year, delivery.month, delivery.day, 6
    )
    assert (
        http.get(f"/api/purchases/{proposal_id}").json()["fulfilment"]["status"]
        == "out_for_delivery"
    )
    again = http.post(
        "/api/demo/clock/advance",
        headers=csrf,
        json={"to": "delivery_day", "idempotency_key": key()},
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "DEMO_CLOCK_NOT_FORWARD"
    with connection() as c:
        event = c.execute("SELECT * FROM demo_clock_events").fetchone()
    assert event["jump_to"] == "delivery_day" and event["jump_days"] is None
    http.post("/api/demo/clock/advance", headers=csrf, json={"days": 1, "idempotency_key": key()})
    assert http.get(f"/api/purchases/{proposal_id}").json()["fulfilment"]["status"] == "delivered"
    nothing = http.post(
        "/api/demo/clock/advance",
        headers=csrf,
        json={"to": "delivery_day", "idempotency_key": key()},
    )
    assert nothing.status_code == 409 and nothing.json()["error"]["code"] == "NO_PENDING_DELIVERY"


def test_to_delivery_day_obeys_the_30_day_limit(
    http, csrf, enabled, pinned, service, buyer, request_data
):
    # The supplier schedule allows a far delivery date; one jump still cannot cross more than 30 days.
    place(service, buyer, request_data, days_ahead=FAR_DAYS)
    r = http.post(
        "/api/demo/clock/advance",
        headers=csrf,
        json={"to": "delivery_day", "idempotency_key": key()},
    )
    assert r.status_code == 422, r.text
    assert http.get("/api/demo/clock").json()["offset_days"] == 0


# --- JNP3-FUL-001..005: the field on the existing responses --------------------------------------


def test_fulfilment_on_the_proposal_the_receipt_and_the_orders_list(
    http, csrf, pinned, service, buyer, request_data
):
    # Not enabled: the status follows REAL time and says so.
    proposal_id, receipt, delivery = place(service, buyer, request_data, days_ahead=2)
    view = http.get(f"/api/purchases/{proposal_id}").json()
    assert set(view["fulfilment"]) == FULFILMENT_KEYS
    assert view["fulfilment"]["status"] == "accepted" and view["fulfilment"]["simulated"] is True
    assert view["fulfilment"]["clock"] == "real"
    assert view["order_status"] == "accepted_mock"  # the order status never changes (JNP3-FUL-002)
    got = http.get(f"/api/purchases/{proposal_id}/receipt").json()
    assert got["order_status"] == "accepted_mock" and got["status"] == "accepted_mock"
    assert got["fulfilment"] == view["fulfilment"]
    assert got["delivery_date"] == str(delivery) and got["destination"] == "hotel-helsinki"
    placed = [
        i
        for i in http.get("/api/orders?status=placed").json()["items"]
        if i["order_id"] == receipt["order_id"]
    ]
    assert placed and placed[0]["fulfilment"] == view["fulfilment"]
    # A basket that is not an order has no fulfilment.
    open_request = dict(request_data, idempotency_key=key())
    open_request["lines"] = [{"product_id": "464398", "amount": "10", "unit": "L"}]
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(open_request)
    )
    assert http.get(f"/api/purchases/{p['proposal_id']}").json()["fulfilment"] is None


def test_a_jump_moves_the_status_through_all_four_states(
    http, csrf, enabled, pinned, service, buyer, request_data
):
    proposal_id, receipt, delivery = place(service, buyer, request_data, days_ahead=2)

    def status():
        view = http.get(f"/api/purchases/{proposal_id}").json()
        assert view["order_status"] == "accepted_mock"
        return view["fulfilment"]

    assert (
        status()["status"] == "accepted" and status()["clock"] == "real"
    )  # offset 0 is the real clock

    def jump(days):
        body = {"days": days, "idempotency_key": key()}
        return http.post("/api/demo/clock/advance", headers=csrf, json=body).status_code

    assert jump(1) == 200  # today 08:00 + 1 day = D-1: preparing
    f = status()
    assert f["status"] == "preparing" and f["clock"] == "demo" and f["simulated"] is True
    assert datetime.fromisoformat(f["next_at"]) == helsinki(
        delivery.year, delivery.month, delivery.day, 6
    )
    assert jump(1) == 200  # D 08:00: out for delivery
    assert status()["status"] == "out_for_delivery"
    assert jump(1) == 200  # D+1: delivered, and final
    f = status()
    assert f["status"] == "delivered" and f["next_status"] is None and f["next_at"] is None
    assert (
        http.get(f"/api/purchases/{proposal_id}/receipt").json()["fulfilment"]["status"]
        == "delivered"
    )
    items = http.get("/api/orders?status=placed").json()["items"]
    assert [i["fulfilment"]["status"] for i in items if i["order_id"] == receipt["order_id"]] == [
        "delivered"
    ]
    http.post("/api/demo/clock/reset", headers=csrf, json={"idempotency_key": key()})
    assert status()["status"] == "accepted"  # a reset goes back to real time


def test_a_jump_leaves_sessions_baskets_and_supplier_calls_on_real_time(
    http, csrf, enabled, pinned, service, buyer, request_data
):
    # An open basket (15 minute lifetime), a prepared proposal and the login session.
    open_request = dict(request_data, idempotency_key=key())
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(open_request)
    )
    r = http.post(
        "/api/demo/clock/advance", headers=csrf, json={"days": 30, "idempotency_key": key()}
    )
    assert r.status_code == 200
    assert http.get("/api/session").status_code == 200  # JNP3-CLK-003: the session is not expired
    view = http.get(f"/api/purchases/{p['proposal_id']}").json()
    assert (
        view["approval_status"] != "expired"
        and view["next_action"]["type"] != "request_fresh_proposal"
    )
    # A new supplier lookup still validates (it compares the supplier's time with the real clock).
    again = service.prepare_order(
        auth.internal_agent(buyer),
        PrepareRequest.model_validate(dict(request_data, idempotency_key=key())),
    )
    assert again["policy_outcome"] == "ready_to_commit"
    confirm = http.post(
        f"/api/purchases/{p['proposal_id']}/confirm",
        headers=csrf,
        json={"proposal_id": p["proposal_id"], "revision": 1, "idempotency_key": key()},
    )
    assert confirm.status_code == 200 and confirm.json()["status"] == "accepted_mock", confirm.text
    with connection() as c:
        stamps = c.execute(
            "SELECT created_at FROM audit_events WHERE proposal_id=%s", (p["proposal_id"],)
        ).fetchall()
    assert stamps and all(
        abs(s["created_at"] - datetime.now(UTC)) < timedelta(minutes=2) for s in stamps
    )


def test_the_clock_is_per_buyer(http, csrf, enabled, pinned, service, buyer, request_data):
    other = add_second_buyer()
    other_http = TestClient(create_app(service))
    with other_http:
        other_csrf = login_headers(other_http, OTHER_APPROVER, OTHER_PASSWORD)
        mine, _, _ = place(service, buyer, request_data, days_ahead=2)
        theirs, _, _ = place(service, other["approver"], request_data, days_ahead=2)
        http.post(
            "/api/demo/clock/advance", headers=csrf, json={"days": 3, "idempotency_key": key()}
        )
        assert http.get(f"/api/purchases/{mine}").json()["fulfilment"]["status"] == "delivered"
        assert other_http.get("/api/demo/clock").json()["offset_days"] == 0
        assert (
            other_http.get(f"/api/purchases/{theirs}").json()["fulfilment"]["status"] == "accepted"
        )
        other_http.post(
            "/api/demo/clock/advance",
            headers=other_csrf,
            json={"days": 1, "idempotency_key": key()},
        )
        assert (
            http.get("/api/demo/clock").json()["offset_days"] == 3
        )  # unchanged by the other buyer
        assert (
            other_http.get(f"/api/purchases/{theirs}").json()["fulfilment"]["status"] == "preparing"
        )
        # Each buyer sees only their own order, as before; the clock added no way across.
        assert other_http.get(f"/api/purchases/{mine}").status_code == 404
    with connection() as c:
        rows = c.execute(
            "SELECT buyer_id, actor_id FROM demo_clock_events ORDER BY created_at"
        ).fetchall()
    assert [(r["buyer_id"], r["actor_id"]) for r in rows] == [
        (BUYER, ACTOR),
        ("other", OTHER_APPROVER),
    ]


def test_the_assistant_cannot_move_the_clock():
    from aimo import agent_tools

    assert not [n for n in dir(agent_tools) if "clock" in n.lower()]  # a customer control only
