"""JNP3-CNF-022/027/030/031/036/037 and POL-012: the customer's schedule functions (Service layer).

A schedule is created only from a past order of the same customer, by an approver, and only for
the exact terms the customer was shown. Fixture supplier data; every order is a mock.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from aimo import auth, schedules
from aimo.db import Problem, connection, js
from aimo.schedule_schemas import (
    ScheduleCreateRequest,
    SchedulePreviewRequest,
    ScheduleReplaceRequest,
)

WEEKLY = {"kind": "weekdays", "weekdays": [0, 1, 2, 3, 4, 5, 6], "every_weeks": 1}


def first_run():
    return date.today() + timedelta(days=3)


def preview_body(order, **changes):
    return SchedulePreviewRequest.model_validate(
        {"order_id": order["order_id"], "recurrence": WEEKLY, "first_run_date": str(first_run())}
        | changes
    )


def create_body(order, terms, **changes):
    return ScheduleCreateRequest.model_validate(
        {
            "order_id": order["order_id"],
            "recurrence": WEEKLY,
            "first_run_date": str(first_run()),
            "price_ceiling_gross": "100.00",
            "agreed_terms_fingerprint": terms["terms_fingerprint"],
            "idempotency_key": str(uuid4()),
        }
        | changes
    )


def make(buyer, service, order, **changes):
    terms = schedules.preview(buyer, preview_body(order), service)
    return schedules.create(buyer, create_body(order, terms, **changes), service)


def refused(code, call, *args):
    with pytest.raises(Problem) as err:
        call(*args)
    assert err.value.code == code
    return err.value


# --- preview and create ---------------------------------------------------------------------


def test_preview_shows_the_exact_terms_and_writes_nothing(buyer, service, placed_order):
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    assert terms["policy_outcome"] == "ready_to_commit" and len(terms["terms_fingerprint"]) == 64
    line = terms["lines"][0]
    assert (line["product_id"], line["amount"], line["unit"]) == ("464306", "10", "L")
    assert line["unit_gross"] and terms["gross_total"] and terms["currency"] == "EUR"
    assert terms["delivery_offset_days"] >= 1
    assert terms["next_dates"][0] == str(first_run()) or terms["next_dates"][0] == first_run()
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM scheduled_authorizations").fetchone()["n"] == 0


def test_create_stores_the_agreed_terms_and_the_one_year_limit(buyer, service, placed_order):
    s = make(buyer, service, placed_order)
    assert s["status"] == "active" and s["next_run_date"] == first_run()
    assert s["valid_until"] == first_run() + timedelta(days=365)
    assert s["price_ceiling_gross"] == "100.00" and s["agreed_gross_total"]
    assert s["lines"][0]["unit_gross"] and s["source_order_id"] == placed_order["order_id"]
    assert s["title"]


def test_the_same_key_returns_the_same_schedule_and_another_body_conflicts(
    buyer, service, placed_order
):
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    body = create_body(placed_order, terms)
    first = schedules.create(buyer, body, service)
    assert schedules.create(buyer, body, service)["id"] == first["id"]
    other = create_body(
        placed_order, terms, idempotency_key=body.idempotency_key, price_ceiling_gross="101.00"
    )
    assert refused("IDEMPOTENCY_CONFLICT", schedules.create, buyer, other, service).status == 409
    assert len(schedules.list_schedules(buyer, 0, 20)["items"]) == 1


def test_only_an_approver_writes(buyer, service, placed_order):
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    for who in (auth.internal_agent(buyer), _scheduler(buyer)):
        refused("FORBIDDEN", schedules.create, who, create_body(placed_order, terms), service)
        refused("FORBIDDEN", schedules.preview, who, preview_body(placed_order), service)
    s = make(buyer, service, placed_order)
    for who in (auth.internal_agent(buyer), _scheduler(buyer)):
        for action in (schedules.cancel, schedules.pause, schedules.resume):
            refused("FORBIDDEN", action, who, s["id"])


def _scheduler(buyer):
    with connection() as c:
        return c.execute(
            "SELECT i.* FROM scheduler_identities s JOIN identities i ON i.id=s.identity_id "
            "WHERE s.buyer_id=%s",
            (buyer["buyer_id"],),
        ).fetchone()


def test_a_stale_or_edited_fingerprint_is_terms_changed(buyer, service, placed_order, connector):
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    connector.price_multiplier = connector.price_multiplier * 2
    err = refused(
        "SCHEDULE_TERMS_CHANGED", schedules.create, buyer, create_body(placed_order, terms), service
    )
    assert err.status == 409


def test_the_ceiling_cannot_be_below_the_agreed_total(buyer, service, placed_order):
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    low = create_body(placed_order, terms, price_ceiling_gross="0.01")
    assert refused("SCHEDULE_CEILING_TOO_LOW", schedules.create, buyer, low, service).status == 422


def other_buyer():
    """A second customer with its own policy and approver."""
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other','999',1)")
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) "
            "SELECT 'other',1,rules FROM policies WHERE buyer_id='demo-hotel'"
        )
        c.execute(
            "INSERT INTO identities VALUES('o','other','approver',true,'!',%s)",
            (js({"currency": "EUR", "max_gross": "5000.00", "exceptions": []}),),
        )
    return {"id": "o", "buyer_id": "other", "role": "approver"}


def test_an_order_of_another_buyer_or_a_missing_order_is_not_found(buyer, service, placed_order):
    refused(
        "NOT_FOUND", schedules.preview, buyer, preview_body({"order_id": str(uuid4())}), service
    )
    refused("NOT_FOUND", schedules.preview, other_buyer(), preview_body(placed_order), service)


def test_a_basket_that_needs_approval_cannot_be_scheduled(buyer, service, request_data):
    from aimo import conversations
    from aimo.schemas import CommitRequest, PrepareRequest

    request_data["lines"] = [{"product_id": "464398", "amount": "10", "unit": "L"}]  # outside scope
    p = service.prepare_order(
        auth.internal_agent(buyer), PrepareRequest.model_validate(request_data)
    )
    receipt = conversations.confirm(
        buyer,
        p["proposal_id"],
        CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4())),
        service,
    )
    order = {"order_id": receipt["order_id"]}
    terms = schedules.preview(buyer, preview_body(order), service)
    assert terms["policy_outcome"] == "approval_required" and terms["blocking_reasons"]
    err = refused(
        "SCHEDULE_NOT_REORDERABLE", schedules.create, buyer, create_body(order, terms), service
    )
    assert err.status == 422


def test_the_first_run_date_cannot_be_in_the_past(buyer, service, placed_order):
    body = preview_body(placed_order, first_run_date=str(date.today() - timedelta(days=1)))
    refused("INVALID_FIRST_RUN_DATE", schedules.preview, buyer, body, service)


def test_at_most_twenty_active_schedules_per_buyer(buyer, service, placed_order, monkeypatch):
    from aimo.config import settings

    monkeypatch.setattr(settings(), "scheduler_max_active_schedules", 2)
    make(buyer, service, placed_order)
    make(buyer, service, placed_order)
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    err = refused(
        "SCHEDULE_LIMIT", schedules.create, buyer, create_body(placed_order, terms), service
    )
    assert err.status == 429


# --- accepted substitutes and the price range (CNF-036, POL-012) ----------------------------


def test_accepted_substitutes_and_the_range_are_stored_with_the_terms(buyer, service, placed_order):
    with connection() as c:  # 464398 is made part of the buyer's approved scope for this test
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) SELECT buyer_id,2,"
            "jsonb_set(rules,'{approved_product_ids}','[\"464306\",\"464398\"]') "
            "FROM policies WHERE buyer_id='demo-hotel' AND version=1"
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    rules = {"464306": {"accepted_substitutes": ["464398"], "price_range_pct": "7.5"}}
    terms = schedules.preview(buyer, preview_body(placed_order, line_rules=rules), service)
    line = terms["lines"][0]
    assert line["price_range_pct"] == "7.50"
    assert [s["product_id"] for s in line["accepted_substitutes"]] == ["464398"]
    assert line["accepted_substitutes"][0]["name"]
    s = schedules.create(buyer, create_body(placed_order, terms, line_rules=rules), service)
    assert s["lines"][0]["accepted_substitutes"][0]["product_id"] == "464398"


@pytest.mark.parametrize(
    "rules",
    [
        {"nope": {"accepted_substitutes": [], "price_range_pct": "1"}},  # not a line of the order
        {"464306": {"accepted_substitutes": ["464306"]}},  # itself
        {"464306": {"accepted_substitutes": ["does-not-exist"]}},  # not in the catalog
        {"464306": {"accepted_substitutes": ["464398"]}},  # catalog yes, outside approved scope
    ],
)
def test_invalid_line_rules_are_refused(buyer, service, placed_order, rules):
    err = refused(
        "INVALID_LINE_RULE",
        schedules.preview,
        buyer,
        preview_body(placed_order, line_rules=rules),
        service,
    )
    assert err.status == 422


# --- cancel, pause, resume, replace, list ---------------------------------------------------


def test_cancel_stops_the_schedule_and_is_repeatable(buyer, service, placed_order):
    s = make(buyer, service, placed_order)
    done = schedules.cancel(buyer, s["id"])
    assert done["status"] == "cancelled" and done["next_run_date"] is None
    assert schedules.cancel(buyer, s["id"])["status"] == "cancelled"
    refused("SCHEDULE_NOT_ACTIVE", schedules.pause, buyer, s["id"])


def test_pause_and_resume_repeat_without_changing_the_terms(buyer, service, placed_order):
    s = make(buyer, service, placed_order)
    paused = schedules.pause(buyer, s["id"])
    assert paused["status"] == "paused" and paused["paused_at"] and paused["next_run_date"]
    assert schedules.pause(buyer, s["id"])["status"] == "paused"
    resumed = schedules.resume(buyer, s["id"])
    assert resumed["status"] == "active" and resumed["paused_at"] is None
    assert schedules.resume(buyer, s["id"])["status"] == "active"
    assert resumed["agreed_gross_total"] == s["agreed_gross_total"]


def test_resume_after_the_year_is_over_is_refused_and_expires_it(buyer, service, placed_order):
    s = make(buyer, service, placed_order)
    with connection() as c:  # a paused schedule whose year ended 35 days ago
        c.execute(
            """INSERT INTO scheduled_authorizations(id,buyer_id,created_by,source_order_id,create_key,
            create_hash,request,agreed_lines,terms_fingerprint,currency,agreed_gross_total,
            price_ceiling_gross,delivery_offset_days,recurrence,first_run_date,valid_until,
            status,paused_at,next_run_date)
            SELECT %s,buyer_id,created_by,source_order_id,'old-year-key',create_hash,request,
            agreed_lines,terms_fingerprint,currency,agreed_gross_total,price_ceiling_gross,
            delivery_offset_days,recurrence,current_date-400,current_date-35,'paused',now(),
            current_date FROM scheduled_authorizations WHERE id=%s""",
            (old_id := uuid4(), s["id"]),
        )
    refused("SCHEDULE_NOT_ACTIVE", schedules.resume, buyer, old_id)
    assert schedules.get(buyer, old_id)["status"] == "expired"


def test_replace_creates_a_new_authorization_that_supersedes_the_old_one(
    buyer, service, placed_order
):
    old = make(buyer, service, placed_order)
    edit = schedules.preview_edit(
        buyer,
        old["id"],
        __import__("aimo.schedule_schemas", fromlist=["x"]).ScheduleEditPreviewRequest(),
        service,
    )
    body = ScheduleReplaceRequest.model_validate(
        {
            "agreed_terms_fingerprint": edit["terms_fingerprint"],
            "idempotency_key": str(uuid4()),
            "price_ceiling_gross": "150.00",
        }
    )
    new = schedules.replace(buyer, old["id"], body, service)
    assert new["id"] != old["id"] and new["supersedes_id"] == old["id"]
    assert new["price_ceiling_gross"] == "150.00" and new["status"] == "active"
    assert schedules.get(buyer, old["id"])["status"] == "superseded"
    assert schedules.get(buyer, old["id"])["replaced_by"] == new["id"]
    assert schedules.replace(buyer, old["id"], body, service)["id"] == new["id"]  # same key


def test_a_stopped_schedule_is_restarted_by_replace_and_keeps_its_history(
    buyer, service, placed_order
):
    from aimo.schedule_schemas import ScheduleEditPreviewRequest

    old = make(buyer, service, placed_order)
    with connection() as c:
        c.execute(
            "UPDATE scheduled_authorizations SET status='stopped',stop_reason='RUN_MISSED',next_run_date=NULL"
        )
    edit = schedules.preview_edit(buyer, old["id"], ScheduleEditPreviewRequest(), service)
    body = ScheduleReplaceRequest.model_validate(
        {"agreed_terms_fingerprint": edit["terms_fingerprint"], "idempotency_key": str(uuid4())}
    )
    new = schedules.replace(buyer, old["id"], body, service)
    assert new["supersedes_id"] == old["id"] and new["status"] == "active"
    assert schedules.get(buyer, old["id"])["status"] == "stopped"
    assert schedules.get(buyer, old["id"])["replaced_by"] == new["id"]


def test_list_and_get_are_scoped_to_the_buyer(buyer, service, placed_order):
    s = make(buyer, service, placed_order)
    page = schedules.list_schedules(buyer, 0, 20)
    assert [x["id"] for x in page["items"]] == [s["id"]] and page["next_offset"] is None
    detail = schedules.get(buyer, s["id"])
    assert detail["runs"] == [] and detail["runs_next_offset"] is None
    other = other_buyer()
    refused("NOT_FOUND", schedules.get, other, s["id"])
    refused("NOT_FOUND", schedules.cancel, other, s["id"])


def test_events_record_who_did_what(buyer, service, placed_order):
    s = make(buyer, service, placed_order)
    schedules.pause(buyer, s["id"])
    schedules.resume(buyer, s["id"])
    schedules.cancel(buyer, s["id"])
    with connection() as c:
        events = [
            (e["event"], e["actor_id"])
            for e in c.execute(
                "SELECT event,actor_id FROM scheduled_authorization_events ORDER BY id"
            ).fetchall()
        ]
    assert events == [(e, "buyer") for e in ("created", "paused", "resumed", "cancelled")]


# --- server-only keys of a source order's stored request -------------------------------------


def order_with_server_constraints(placed_order):
    """A past order whose stored request carries the server-only `constraints` key (PR #133)."""
    with connection() as c:
        old = c.execute(
            "SELECT p.agent_id,r.* FROM proposals p JOIN proposal_revisions r ON r.proposal_id=p.id "
            "WHERE p.id=%s AND r.revision=1",
            (placed_order["proposal_id"],),
        ).fetchone()
        pid, oid = uuid4(), uuid4()
        c.execute(
            "INSERT INTO proposals(id,buyer_id,agent_id,current_revision) VALUES(%s,'demo-hotel',%s,1)",
            (pid, old["agent_id"]),
        )
        request = old["request"] | {
            "constraints": [
                {"name": "budget_gross", "value": "500", "source": "chat", "confirmed": True}
            ]
        }
        c.execute(
            "INSERT INTO proposal_revisions(proposal_id,revision,policy_version,request,snapshot,"
            "fingerprint,policy_outcome,reasons,required_exceptions,expires_at) "
            "SELECT %s,1,policy_version,%s,snapshot,fingerprint,policy_outcome,reasons,"
            "required_exceptions,expires_at FROM proposal_revisions WHERE proposal_id=%s AND revision=1",
            (pid, js(request), placed_order["proposal_id"]),
        )
        c.execute(
            "INSERT INTO orders(id,proposal_id,buyer_id,revision,receipt) VALUES(%s,%s,'demo-hotel',1,'{}')",
            (oid, pid),
        )
    return {"order_id": str(oid), "proposal_id": str(pid)}


def test_a_source_orders_server_only_constraints_never_enter_the_standing_order(
    buyer, service, placed_order
):
    source = order_with_server_constraints(placed_order)
    s = make(buyer, service, source)
    with connection() as c:
        stored = c.execute(
            "SELECT request FROM scheduled_authorizations WHERE id=%s", (s["id"],)
        ).fetchone()["request"]
    assert "constraints" not in stored  # the limits are the ones the customer agrees now
