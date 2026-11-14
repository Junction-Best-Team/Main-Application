"""Scheduled (standing) re-orders, WS-E. Every order placed here is a MOCK order.

The run engine. `run_due_schedules` does one step of one run per call, so a worker iteration stays
far below its 270 second health limit even when the supplier is slow:

  materialise  create the run of each due date (idempotent: unique authorization + date)
  due          prepare the basket as the buyer's internal agent and compare it with the terms
               the customer agreed; plan an accepted substitute when a line cannot be used
  prepared     commit as the scheduler identity, gated by ensure_commit_allowed
  committed / disrupted (the schedule stops, the customer is told) / skipped (a pause)

The scheduler identity commits only against a valid, active authorization; it never creates,
edits or restarts one (those are the customer's functions in aimo.schedules).
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from aimo import auth as auth_module
from aimo import cancellations
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, js
from aimo.observability import event, failure
from aimo.schemas import CommitRequest, LookupRequest, PrepareRequest
from aimo.upstream import HELSINKI

ONE_DAY = timedelta(days=1)


def helsinki_today(now=None):
    """The Helsinki calendar date: every schedule date and every run is in this zone."""
    return (now or datetime.now(timezone.utc)).astimezone(HELSINKI).date()


# --- Terms fingerprint ---------------------------------------------------------------------
# "The same terms" of a standing order. material_fingerprint (purchases.py) cannot be used: it
# hashes request_id, delivery_date, supplier cutoff and full product facts, so two runs on
# different dates never match. The field set is these constants only; widening it (for example
# adding product facts, owner question Q-80) is a change here and nowhere else.
TERMS_REQUEST_FIELDS = ("destination",)
TERMS_LINE_FIELDS = ("product_id", "substitutes_for", "quantity", "deposits", "price", "deleted")
TERMS_QUANTITY_FIELDS = ("requested_amount", "requested_unit", "sales_unit", "sales_quantity")
TERMS_DEPOSIT_FIELDS = (
    "material",
    "quantity",
    "unit",
    "priced_sales_quantity",
    "sales_unit",
    "net",
    "gross",
)
TERMS_PRICE_FIELDS = ("net", "gross", "tax_rate")


def terms_view(request, snapshot):
    """The commercial terms of one proposal revision, free of dates, times, stock and facts."""
    lines = []
    for line in snapshot["lines"]:
        evidence = line["commercial_evidence"]
        values = {
            "product_id": line["product_id"],
            "substitutes_for": line.get("substitutes_for"),
            "quantity": {k: line["quantity"].get(k) for k in TERMS_QUANTITY_FIELDS},
            "deposits": [
                {k: d.get(k) for k in TERMS_DEPOSIT_FIELDS} for d in line["deposit_lines"]
            ],
            "price": {k: evidence.get(k) for k in TERMS_PRICE_FIELDS},
            "deleted": bool(line["product_evidence"].get("deleted")),
        }
        lines.append({k: values[k] for k in TERMS_LINE_FIELDS})
    return {
        **{k: request.get(k) for k in TERMS_REQUEST_FIELDS},
        "currency": snapshot["currency"],
        "lines": sorted(lines, key=lambda line: line["product_id"]),
    }


def terms_fingerprint(request, snapshot):
    return fingerprint(terms_view(request, snapshot))


# --- Recurrence ----------------------------------------------------------------------------
# {"kind": "days", "interval": 4}                    every 4 days from the first run date
# {"kind": "weekdays", "weekdays": [1, 4], "every_weeks": 1}   Tue and Fri (0 = Monday)
# The series starts at first_run_date and never goes past valid_until.
MAX_INTERVAL_DAYS = 365
MAX_EVERY_WEEKS = 52


def normalize_recurrence(recurrence):
    bad = Problem("INVALID_RECURRENCE", "Choose a supported delivery pattern.", 422)
    if not isinstance(recurrence, dict):
        raise bad
    kind = recurrence.get("kind")
    if kind == "days":
        interval = recurrence.get("interval")
        if type(interval) is not int or not 1 <= interval <= MAX_INTERVAL_DAYS:
            raise bad
        return {"kind": "days", "interval": interval}
    if kind == "weekdays":
        days, weeks = recurrence.get("weekdays"), recurrence.get("every_weeks", 1)
        if (
            not isinstance(days, list)
            or not days
            or any(type(d) is not int or not 0 <= d <= 6 for d in days)
            or type(weeks) is not int
            or not 1 <= weeks <= MAX_EVERY_WEEKS
        ):
            raise bad
        return {"kind": "weekdays", "weekdays": sorted(set(days)), "every_weeks": weeks}
    raise bad


def next_dates(recurrence, first_run_date, valid_until, *, after=None, limit=1):
    """The next `limit` scheduled dates strictly after `after` (all from the start if None),
    never before first_run_date and never after valid_until. Pure: no clock, no database."""
    rule = normalize_recurrence(recurrence)
    found, day = [], first_run_date if after is None else max(first_run_date, after + ONE_DAY)
    if rule["kind"] == "days":
        steps = -(-(day - first_run_date).days // rule["interval"])  # ceiling
        day = first_run_date + timedelta(days=steps * rule["interval"])
    first_monday = first_run_date - timedelta(days=first_run_date.weekday())
    while day <= valid_until and len(found) < limit:
        if rule["kind"] == "days":
            found.append(day)
            day += timedelta(days=rule["interval"])
            continue
        week = ((day - timedelta(days=day.weekday())) - first_monday).days // 7
        if day.weekday() in rule["weekdays"] and week % rule["every_weeks"] == 0:
            found.append(day)
        day += ONE_DAY
    return found


# --- Comparing a prepared basket with the agreed terms -------------------------------------
UNAVAILABLE_CODES = {
    "INSUFFICIENT_STOCK", "SALES_BLOCK", "CUTOFF_PASSED", "DELIVERY_TOO_LATE", "DELIVERY_UNRESOLVED",
    "UNVERIFIED_STOCK", "AVAILABILITY_UNIT_UNKNOWN",
}  # fmt: skip
WITHDRAWN_CODES = {"PRODUCT_DELETED", "PRODUCT_UNKNOWN"}
BLOCKING = ("denied", "unresolved")
DISRUPTION_CODES = {
    "unavailable": "PRODUCT_UNAVAILABLE",
    "withdrawn": "PRODUCT_WITHDRAWN",
    "price_outside_range": "PRICE_OUTSIDE_RANGE",
}


def gross_of(line):
    value = (line.get("commercial_evidence") or {}).get("gross")
    return None if value is None else Decimal(value)


def percent_off(current, agreed):
    return abs(current - agreed) * 100 / agreed


def compare(auth, request, snapshot, outcome, plan=()):
    """Pure. Does a prepared basket match what the customer agreed (CNF-024, CNF-036, POL-012)?

    A line matches when its product is usable and its unit gross price is within the customer's
    percentage range of the agreed price, or when it is a planned accepted substitute that is
    usable and within the range of the ORIGINAL agreed price. Returns the verdict with a status for
    every line, the substitutions used and the first disruption code."""
    swaps = {item["product_id"]: item["substitute_product_id"] for item in plan}
    current = {line["product_id"]: line for line in snapshot["lines"]}
    blocked = {}
    for reason in snapshot["reasons"]:
        if reason.get("product_id") and reason["severity"] in BLOCKING:
            blocked.setdefault(reason["product_id"], set()).add(reason["code"])
    lines, substitutions, codes, wanted = [], [], [], set()
    for agreed in auth["agreed_lines"]:
        pid = agreed["product_id"]
        target = swaps.get(pid, pid)
        wanted.add(target)
        rule = (auth["line_rules"] or {}).get(pid, {})
        limit = Decimal(rule.get("price_range_pct", "0"))
        before = Decimal(agreed["unit_gross"])
        row = {"product_id": pid, "name": agreed["name"], "agreed_gross": str(before)}
        line = current.get(target)
        problems = blocked.get(target, set())
        quantity = (line or {}).get("quantity") or {}
        if line is None or (
            Decimal(quantity.get("requested_amount") or "0") != Decimal(agreed["amount"])
            or quantity.get("requested_unit") != agreed["unit"]
        ):
            status = "unavailable"
        elif problems & WITHDRAWN_CODES:
            status = "withdrawn"
        elif problems:
            status = "unavailable"
        else:
            now_gross = gross_of(line)
            row["current_gross"] = None if now_gross is None else str(now_gross)
            if now_gross is None:
                status = "unavailable"
            elif percent_off(now_gross, before) > limit:
                status = "price_outside_range"
            elif target != pid:
                status = "substituted"
            elif now_gross == before:
                status = "available_same_price"
            else:
                status = "price_within_range"
        row["status"] = status
        if target != pid:
            row["substitute_product_id"] = target
            gross = row.get("current_gross")
            row["note"] = f"Used {target} instead of {pid}" + (
                f" (price {Decimal(gross) - before:+.2f} per unit)" if gross else ""
            )
            if status == "substituted":
                substitutions.append(row | {"name": line["name"]})
        if status in DISRUPTION_CODES:
            codes.append(DISRUPTION_CODES[status])
        lines.append(row)
    if set(current) - wanted:
        codes.append("RUN_TERMS_CHANGED")
    if request.get("destination") != (auth["request"] or {}).get("destination"):
        codes.append("RUN_TERMS_CHANGED")
    total = None if snapshot["gross_total"] is None else Decimal(snapshot["gross_total"])
    if total is not None and total > Decimal(auth["price_ceiling_gross"]):
        codes.append("CEILING_EXCEEDED")
    if not codes and outcome != "ready_to_commit":
        codes.append("POLICY_NOT_READY")
    return {
        "ok": not codes,
        "codes": list(dict.fromkeys(codes)),
        "lines": lines,
        "substitutions": substitutions,
        "agreed_gross_total": str(auth["agreed_gross_total"]),
        "current_gross_total": None if total is None else str(total),
    }


def reason_of(verdict):
    return {k: verdict[k] for k in ("codes", "lines", "agreed_gross_total", "current_gross_total")}


# --- The commit gate -----------------------------------------------------------------------


def refuse(message="A scheduler identity commits only against a valid scheduled authorization."):
    raise Problem("SCHEDULE_NOT_AUTHORIZED", message, 403)


def owns_proposal(c, proposal_id, buyer_id):
    return (
        c.execute(
            "SELECT 1 FROM scheduled_runs WHERE proposal_id=%s AND buyer_id=%s",
            (proposal_id, buyer_id),
        ).fetchone()
        is not None
    )


def ensure_commit_allowed(c, identity, p, r, snapshot, evaluated):
    """CNF-023/024: the scheduler may commit this proposal only if, right now and under the buyer
    lock, a prepared run owns it, its authorization is active and unexpired, the customer who
    created it is still an active approver, and the fresh terms match what was agreed."""
    run = c.execute(
        "SELECT * FROM scheduled_runs WHERE proposal_id=%s AND buyer_id=%s AND status='prepared'",
        (p["id"], identity["buyer_id"]),
    ).fetchone()
    if not run:
        refuse()
    auth = c.execute(
        "SELECT * FROM scheduled_authorizations WHERE id=%s AND buyer_id=%s FOR SHARE",
        (run["authorization_id"], identity["buyer_id"]),
    ).fetchone()
    if not auth or auth["status"] != "active" or auth["valid_until"] < helsinki_today():
        refuse("The scheduled authorization is not active.")
    customer = c.execute(
        "SELECT 1 FROM identities WHERE id=%s AND buyer_id=%s AND active AND role='approver'",
        (auth["created_by"], identity["buyer_id"]),
    ).fetchone()
    if not customer:
        refuse("The customer who created the schedule is no longer active.")
    verdict = compare(
        auth, r["request"], snapshot, evaluated["policy_outcome"], run["substitutions"]
    )
    if not verdict["ok"]:
        refuse("The current terms differ from the agreed terms.")


def receipt_note(c, proposal_id):
    run = c.execute("SELECT * FROM scheduled_runs WHERE proposal_id=%s", (proposal_id,)).fetchone()
    return {
        "run_id": str(run["id"]),
        "schedule_id": str(run["authorization_id"]),
        "scheduled_date": str(run["scheduled_date"]),
        "delivery_date": str(run["delivery_date"]),
        "ran_late": "RAN_LATE" in ((run["reason"] or {}).get("codes") or []),
        "substitutions": run["substitutions"] or [],
    }


# --- The engine ----------------------------------------------------------------------------
LOCK_KEY = 893021
LEASE_SECONDS = 240
BACKOFF_SECONDS = (120, 240, 480, 900)
TRANSIENT = {"UPSTREAM_UNAVAILABLE", "UPSTREAM_RATE_LIMITED", "DATABASE_BUSY"}
ENDED = ("cancelled", "superseded", "expired", "stopped")


def run_event(c, run_id, actor, name, detail=None):
    c.execute(
        "INSERT INTO scheduled_run_events(run_id,actor_id,event,detail) VALUES(%s,%s,%s,%s)",
        (run_id, actor, name, js(detail or {})),
    )


def auth_event(c, aid, name, detail=None):
    c.execute(
        "INSERT INTO scheduled_authorization_events(authorization_id,actor_id,event,detail) "
        "VALUES(%s,'scheduler',%s,%s)",
        (aid, name, js(detail or {})),
    )


def cancel_request(c, proposal_id, buyer_id, reason, run_id):
    """Record that an order request will not be placed (never for a placed order)."""
    if c.execute("SELECT 1 FROM orders WHERE proposal_id=%s", (proposal_id,)).fetchone():
        return
    # One writer for cancellations: aimo.cancellations (first record stands, row-locked).
    cancellations.cancel_request(
        c, proposal_id, buyer_id, reason, run_id=run_id, by=scheduler_identity_id(c, buyer_id)
    )


def scheduler_identity_id(c, buyer_id):
    row = c.execute(
        """SELECT i.id FROM scheduler_identities s JOIN identities i ON i.id=s.identity_id
        WHERE s.buyer_id=%s AND i.active AND i.role='scheduler'""",
        (buyer_id,),
    ).fetchone()
    return row["id"] if row else None


def materialise(now=None):
    """Create the run of each due date. Short, idempotent and serialized across replicas."""
    now = now or datetime.now(timezone.utc)
    today = helsinki_today(now)
    after_hour = now.astimezone(HELSINKI).hour >= settings().scheduler_run_after_hour
    created = 0
    with connection() as c:
        c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        for row in c.execute(
            """UPDATE scheduled_authorizations SET status='expired',next_run_date=NULL,paused_at=NULL,
            updated_at=%s WHERE status IN ('active','paused') AND valid_until < %s RETURNING id""",
            (now, today),
        ).fetchall():
            auth_event(c, row["id"], "expired")
        due = c.execute(
            """SELECT * FROM scheduled_authorizations WHERE status IN ('active','paused')
            AND next_run_date IS NOT NULL AND next_run_date <= %s
            ORDER BY next_run_date,id LIMIT %s FOR UPDATE SKIP LOCKED""",
            (today, settings().scheduler_max_runs_per_pass),
        ).fetchall()
        for auth in due:
            created += open_dates(c, auth, today, after_hour, now)
    return created


def open_dates(c, auth, today, after_hour, now):
    """Open the runs of one authorization. A paused one skips every date up to today."""
    made, day = 0, auth["next_run_date"]
    while day is not None and day <= today:
        if day == today and not after_hour:
            break
        run_id, late, delivery = uuid4(), False, day + timedelta(days=auth["delivery_offset_days"])
        if auth["status"] == "paused":
            state, code = "skipped", "PAUSED"
        elif not within_grace(day, now):
            state, code = "disrupted", "RUN_MISSED"
        else:
            state, code = "due", None
            if run_age(day, now) > LATE_AFTER:  # CNF-039: a short outage runs the date late
                late = True
                delivery = max(delivery, today + ONE_DAY)  # tomorrow at the earliest
        row = c.execute(
            """INSERT INTO scheduled_runs(id,authorization_id,buyer_id,scheduled_date,delivery_date,
            status,reason_code,reason) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(authorization_id,scheduled_date) DO NOTHING RETURNING *""",
            (
                run_id,
                auth["id"],
                auth["buyer_id"],
                day,
                delivery,
                state,
                code,
                js({"codes": [code], "lines": []}) if code else None,
            ),
        ).fetchone()
        following = next_dates(
            auth["recurrence"], auth["first_run_date"], auth["valid_until"], after=day
        )
        day = following[0] if following else None
        c.execute(
            "UPDATE scheduled_authorizations SET next_run_date=%s,updated_at=%s WHERE id=%s",
            (day, now, auth["id"]),
        )
        if row:
            made += 1
            if late:
                c.execute(
                    "UPDATE scheduled_runs SET reason=%s WHERE id=%s",
                    (js({"codes": ["RAN_LATE"], "lines": []}), row["id"]),
                )
            run_event(
                c,
                row["id"],
                "scheduler",
                "created",
                {"status": state}
                | ({"late": True, "delivery_date": str(delivery)} if late else {}),
            )
            if state == "disrupted":
                stop(c, row, auth, code, now)
                break
    return made


LATE_AFTER = timedelta(minutes=15)  # a run started later than this after its run time is "late"


def run_age(day, now):
    """How long after its run time (the run hour, Helsinki, on that date) `now` is."""
    run_time = datetime.combine(
        day, datetime.min.time().replace(hour=settings().scheduler_run_after_hour), HELSINKI
    )
    return now - run_time


def within_grace(day, now):
    """CNF-039: a date still runs, late, while `now` is at most `scheduler_grace_hours` after its run
    time. A short outage (under 6 hours by default) is therefore not a disruption; a longer one is
    RUN_MISSED. Set SCHEDULER_GRACE_HOURS=30 to let an outage across midnight run late too."""
    return run_age(day, now) <= timedelta(hours=settings().scheduler_grace_hours)


def open_demo_run(c, auth, now):
    """DEMO ONLY (CNF-038): today's run for this authorization, due at once. Idempotent per date."""
    today = helsinki_today(now)
    row = c.execute(
        """INSERT INTO scheduled_runs(id,authorization_id,buyer_id,scheduled_date,delivery_date)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT(authorization_id,scheduled_date) DO NOTHING RETURNING *""",
        (
            uuid4(),
            auth["id"],
            auth["buyer_id"],
            today,
            today + timedelta(days=auth["delivery_offset_days"]),
        ),
    ).fetchone()
    if row:
        run_event(c, row["id"], "scheduler", "created", {"status": "due", "demo": True})
        run_event(c, row["id"], "scheduler", "demo_run_now", {"demo": True})
    return row


def stop(c, run, auth, code, now):
    """The schedule stops after a disruption (CNF-030); the customer restarts or replaces it."""
    c.execute(
        """UPDATE scheduled_authorizations SET status='stopped',stop_reason=%s,next_run_date=NULL,
        paused_at=NULL,updated_at=%s WHERE id=%s AND status IN ('active','paused')""",
        (code, now, auth["id"]),
    )
    auth_event(c, auth["id"], "stopped", {"run_id": str(run["id"]), "code": code})


def claim_run(now):
    with connection() as c:
        run = c.execute(
            """SELECT * FROM scheduled_runs WHERE status IN ('due','prepared')
            AND (lease_until IS NULL OR lease_until <= %s)
            ORDER BY scheduled_date,created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""",
            (now,),
        ).fetchone()
        if not run:
            return None
        return c.execute(
            "UPDATE scheduled_runs SET lease_until=%s,updated_at=%s WHERE id=%s RETURNING *",
            (now + timedelta(seconds=LEASE_SECONDS), now, run["id"]),
        ).fetchone()


def run_due_schedules(service, *, now=None, materialise_first=True):
    """One step of one run. Returns whether any work was done."""
    now = now or datetime.now(timezone.utc)
    created = materialise(now) if materialise_first else 0
    run = claim_run(now)
    if run is None:
        return created > 0
    try:
        step(service, run, now)
    except Exception as exc:
        # A failed step is retried with backoff; after the limit the run is a disruption.
        event("scheduler.step_failed", level=logging.WARNING, run_id=str(run["id"]), **failure(exc))
        retry_later(
            run,
            getattr(exc, "code", "RUN_FAILED") if isinstance(exc, Problem) else "RUN_FAILED",
            now,
        )
    return True


def retry_later(run, code, now):
    attempts = run["attempts"] + 1
    with connection() as c:
        if attempts >= settings().scheduler_max_attempts:
            auth = c.execute(
                "SELECT * FROM scheduled_authorizations WHERE id=%s FOR UPDATE",
                (run["authorization_id"],),
            ).fetchone()
            disrupt(c, run, auth, code, {"codes": [code], "lines": []}, now)
            return
        wait = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        c.execute(
            "UPDATE scheduled_runs SET attempts=%s,lease_until=%s,updated_at=%s WHERE id=%s",
            (attempts, now + timedelta(seconds=wait), now, run["id"]),
        )
        run_event(c, run["id"], "scheduler", "retry", {"code": code, "attempt": attempts})


def disrupt(c, run, auth, code, reason, now):
    c.execute(
        """UPDATE scheduled_runs SET status='disrupted',reason_code=%s,reason=%s,lease_until=NULL,
        updated_at=%s WHERE id=%s""",
        (code, js(reason), now, run["id"]),
    )
    if run["proposal_id"]:
        cancel_request(c, run["proposal_id"], run["buyer_id"], "run_disrupted", run["id"])
    run_event(c, run["id"], "scheduler", "disrupted", {"code": code})
    stop(c, run, auth, code, now)
    start_customer_chat(c, run, auth, code, reason, now)


EXPLANATION = {
    "PRODUCT_UNAVAILABLE": "a product is not available for this delivery",
    "PRODUCT_WITHDRAWN": "a product has been withdrawn from the catalog",
    "PRICE_OUTSIDE_RANGE": "a price is outside the range you agreed",
    "CEILING_EXCEEDED": "the total is above your price ceiling",
    "RUN_TERMS_CHANGED": "the products or terms of the order changed",
    "POLICY_NOT_READY": "the purchasing policy does not allow it to be placed without a decision",
    "RUN_MISSED": "the date passed before the order could be placed",
    "AUTHORIZATION_WITHDRAWN": "the customer who set up the standing order is no longer active",
    "SCHEDULER_NOT_CONFIGURED": "the standing-order service is not set up for this account",
    "UPSTREAM_UNAVAILABLE": "the supplier could not be reached",
    "UPSTREAM_RATE_LIMITED": "the supplier is limiting requests",
}
NOTICE_PREFIX = "Standing-order notice (written by the system, not typed by the customer)\n"


def provider_message(role, text):
    """A stored message as the model provider sees it: the system notice arrives as a user turn."""
    if role == "system":
        return {"role": "user", "content": NOTICE_PREFIX + text}
    return {"role": role, "content": text}


def line_summary(auth, reason):
    seen = {line["product_id"]: line for line in (reason or {}).get("lines", [])}
    out = []
    for agreed in auth["agreed_lines"]:
        line = seen.get(agreed["product_id"], {})
        status = line.get("status", "not_checked")
        parts = [
            f"- {agreed['product_id']} {agreed['name']}, {agreed['amount']} {agreed['unit']}: "
            f"{status}; agreed unit price {agreed['unit_gross']}"
        ]
        if line.get("current_gross"):
            parts.append(f", now {line['current_gross']}")
        if line.get("substitute_product_id"):
            parts.append(f", substitute {line['substitute_product_id']}")
        out.append("".join(parts))
    return out


def disruption_text(run, auth, code, reason):
    lines = "\n".join(line_summary(auth, reason))
    return (
        f"Your standing order for {run['scheduled_date']} (delivery {run['delivery_date']}) was not "
        f"placed and the schedule has stopped: {EXPLANATION.get(code, code)} ({code}).\n"
        f"Lines of the standing order (unit prices are gross, per sales unit):\n{lines}\n"
        "Instructions for the assistant: every line marked available_same_price or "
        "price_within_range is a confirmed, valid ingredient; keep it. For each other line find "
        "alternatives (substitution candidates, product search), explain the price differences "
        "against the agreed unit price and ask which replacement the customer wants. Then prepare "
        "the revised order so the customer can confirm it in the product; nothing is ordered "
        "until the customer confirms. All orders are mocks."
    )


def fallback_text(run, auth, code, reason):
    lines = "\n".join(line_summary(auth, reason))
    return (
        f"The standing order for {run['scheduled_date']} could not be placed and the schedule has "
        f"stopped: {EXPLANATION.get(code, code)}. I could not look up alternatives just now.\n"
        f"{lines}\nTell me which replacements you want and I will prepare the order for you to "
        "confirm. Nothing has been ordered."
    )


def start_customer_chat(c, run, auth, code, reason, now):
    """CNF-028/033: open the revision chat with a system-authored first message. The ordinary
    worker path then wakes the agent. One conversation per run, however often this is called."""
    current = c.execute(
        "SELECT conversation_id FROM scheduled_runs WHERE id=%s", (run["id"],)
    ).fetchone()
    if current and current["conversation_id"]:
        return
    approver = c.execute(
        """SELECT id FROM identities WHERE buyer_id=%s AND active AND role='approver'
        ORDER BY (id = %s) DESC,id LIMIT 1""",
        (run["buyer_id"], auth["created_by"]),
    ).fetchone()
    if not approver:
        return run_event(c, run["id"], "scheduler", "chat_not_started", {"code": code})
    key = f"sched-run-{run['id']}"
    cid, tid = uuid4(), uuid4()
    c.execute(
        """INSERT INTO conversations(id,buyer_id,title,create_key,create_hash)
        VALUES(%s,%s,%s,%s,%s)""",
        (
            cid,
            run["buyer_id"],
            f"Standing order {run['scheduled_date']}: needs your attention",
            key,
            fingerprint({"run": str(run["id"])}),
        ),
    )
    c.execute(
        """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
        attempt,requested_by,worker_attempts,submitted_by) VALUES(%s,%s,%s,%s,'queued',%s,%s,%s,0,NULL)""",
        (tid, cid, key, fingerprint({"run": str(run["id"])}), now, uuid4(), approver["id"]),
    )
    c.execute(
        "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'system',%s)",
        (cid, tid, disruption_text(run, auth, code, reason)),
    )
    c.execute("UPDATE scheduled_runs SET conversation_id=%s WHERE id=%s", (cid, run["id"]))
    run_event(c, run["id"], "scheduler", "chat_started", {"conversation_id": str(cid)})


def settle_failed_system_turn(c, turn_id, conversation_id):
    """Trap T1: a failed system-authored turn has no customer message to retry, so the chat would
    refuse new messages for good. Answer it with a deterministic message and close the turn."""
    system = c.execute(
        """SELECT 1 FROM conversation_messages WHERE turn_id=%s AND role='system'
        AND NOT EXISTS (SELECT 1 FROM conversation_messages WHERE turn_id=%s AND role='user')""",
        (turn_id, turn_id),
    ).fetchone()
    if not system:
        return False
    row = c.execute(
        """SELECT r.*,a.agreed_lines FROM scheduled_runs r
        JOIN scheduled_authorizations a ON a.id=r.authorization_id WHERE r.conversation_id=%s""",
        (conversation_id,),
    ).fetchone()
    text = (
        fallback_text(row, row, row["reason_code"], row["reason"])
        if row
        else "This notice could not be completed. Tell me what you would like to order."
    )
    c.execute(
        """INSERT INTO conversation_messages(conversation_id,turn_id,role,text)
        VALUES(%s,%s,'assistant',%s) ON CONFLICT(turn_id,role) DO NOTHING""",
        (conversation_id, turn_id, text),
    )
    c.execute("UPDATE conversation_turns SET state='complete' WHERE id=%s", (turn_id,))
    c.execute("UPDATE conversations SET updated_at=now() WHERE id=%s", (conversation_id,))
    return True


def skip(c, run, code, now, cancel_reason=None):
    c.execute(
        """UPDATE scheduled_runs SET status='skipped',reason_code=%s,reason=%s,lease_until=NULL,
        updated_at=%s WHERE id=%s""",
        (code, js({"codes": [code], "lines": []}), now, run["id"]),
    )
    if run["proposal_id"] and cancel_reason:
        cancel_request(c, run["proposal_id"], run["buyer_id"], cancel_reason, run["id"])
    run_event(c, run["id"], "scheduler", "skipped", {"code": code})


def step(service, run, now):
    with connection() as c:
        auth = c.execute(
            "SELECT * FROM scheduled_authorizations WHERE id=%s", (run["authorization_id"],)
        ).fetchone()
        sched = scheduler_identity_id(c, run["buyer_id"])
        customer = c.execute(
            "SELECT 1 FROM identities WHERE id=%s AND buyer_id=%s AND active AND role='approver'",
            (auth["created_by"], run["buyer_id"]),
        ).fetchone()
    with connection() as c:
        if auth["status"] == "paused":
            return skip(c, run, "PAUSED", now, "customer_cancelled")
        if auth["status"] in ENDED or auth["valid_until"] < helsinki_today(now):
            return skip(
                c, run, "AUTHORIZATION_" + auth["status"].upper(), now, "customer_cancelled"
            )
        if sched is None:
            auth = c.execute(
                "SELECT * FROM scheduled_authorizations WHERE id=%s FOR UPDATE", (auth["id"],)
            ).fetchone()
            return disrupt(
                c,
                run,
                auth,
                "SCHEDULER_NOT_CONFIGURED",
                {"codes": ["SCHEDULER_NOT_CONFIGURED"], "lines": []},
                now,
            )
        if not customer:
            return disrupt(
                c,
                run,
                auth,
                "AUTHORIZATION_WITHDRAWN",
                {"codes": ["AUTHORIZATION_WITHDRAWN"], "lines": []},
                now,
            )
    (prepare if run["status"] == "due" else commit)(service, run, auth, sched, now)


def basket(auth, run, plan):
    """The request of one run: the agreed lines with this date's delivery, planned swaps applied."""
    swaps = {item["product_id"]: item["substitute_product_id"] for item in plan}
    request = {k: v for k, v in auth["request"].items() if k != "constraints"}  # server-only key
    request["lines"] = [
        line | {"product_id": swaps.get(line["product_id"], line["product_id"])}
        for line in request["lines"]
    ]
    return request | {
        "request_id": f"standing-{str(auth['id'])[:8]}-{run['scheduled_date']}",
        "delivery_date": str(run["delivery_date"]),
    }


def prepare(service, run, auth, sched, now):
    plan = run["substitutions"] or []
    agent = auth_module.internal_agent({"buyer_id": run["buyer_id"]})
    request = basket(auth, run, plan) | {
        "idempotency_key": f"sched-{run['id']}-{run['attempts']}-{'plan' if plan else 'agreed'}"
    }
    proposal = service.prepare_order(agent, PrepareRequest.model_validate(request))
    verdict = compare(
        auth, proposal["request"], proposal["snapshot"], proposal["policy_outcome"], plan
    )
    with connection() as c:
        if verdict["ok"]:
            c.execute(
                """UPDATE scheduled_runs SET status='prepared',proposal_id=%s,substitutions=%s,
                lease_until=NULL,updated_at=%s WHERE id=%s""",
                (proposal["proposal_id"], js(verdict["substitutions"]), now, run["id"]),
            )
            return run_event(
                c, run["id"], sched, "prepared", {"proposal_id": proposal["proposal_id"]}
            )
        c.execute(
            "UPDATE scheduled_runs SET proposal_id=%s WHERE id=%s",
            (proposal["proposal_id"], run["id"]),
        )
    swaps = [] if plan else choose_substitutes(service, agent, auth, run, verdict)
    with connection() as c:
        auth_row = c.execute(
            "SELECT * FROM scheduled_authorizations WHERE id=%s FOR UPDATE", (auth["id"],)
        ).fetchone()
        run = c.execute(
            "SELECT * FROM scheduled_runs WHERE id=%s FOR UPDATE", (run["id"],)
        ).fetchone()
        if swaps:
            cancel_request(c, proposal["proposal_id"], run["buyer_id"], "run_retry", run["id"])
            c.execute(
                """UPDATE scheduled_runs SET substitutions=%s,proposal_id=NULL,lease_until=NULL,
                updated_at=%s WHERE id=%s""",
                (js(swaps), now, run["id"]),
            )
            return run_event(c, run["id"], sched, "substitution_planned", {"lines": swaps})
        disrupt(c, run, auth_row, verdict["codes"][0], reason_of(verdict), now)


def choose_substitutes(service, agent, auth, run, verdict):
    """For each unusable line with accepted substitutes, the available one whose unit price is
    closest to the ORIGINAL agreed price and inside the customer's range (POL-012)."""
    wanted = {}
    for line in verdict["lines"]:
        rule = (auth["line_rules"] or {}).get(line["product_id"], {})
        if line["status"] in DISRUPTION_CODES and rule.get("accepted_substitutes"):
            wanted[line["product_id"]] = rule
    if not wanted or set(verdict["codes"]) - set(DISRUPTION_CODES.values()):
        return []
    ids = sorted({s for rule in wanted.values() for s in rule["accepted_substitutes"]})
    found = service.check_price_and_availability(
        agent, LookupRequest(product_ids=ids, delivery_date=run["delivery_date"])
    )["products"]
    agreed = {line["product_id"]: line for line in auth["agreed_lines"]}
    swaps = []
    for pid, rule in wanted.items():
        before = Decimal(agreed[pid]["unit_gross"])
        options = []
        for candidate in rule["accepted_substitutes"]:
            evidence = found.get(candidate) or {}
            if evidence.get("reasons") or evidence.get("gross") is None:
                continue
            price = Decimal(evidence["gross"])
            if percent_off(price, before) <= Decimal(rule.get("price_range_pct", "0")):
                options.append((abs(price - before), candidate, price))
        if not options:
            return []
        _, best, price = min(options)
        swaps.append(
            {
                "product_id": pid,
                "name": agreed[pid]["name"],
                "status": "substituted",
                "agreed_gross": str(before),
                "current_gross": str(price),
                "substitute_product_id": best,
            }
        )
    return swaps


def commit(service, run, auth, sched, now):
    with connection() as c:
        revision = c.execute(
            "SELECT current_revision FROM proposals WHERE id=%s", (run["proposal_id"],)
        ).fetchone()["current_revision"]
    identity = scheduler_row(sched)
    body = CommitRequest(
        proposal_id=run["proposal_id"],
        revision=revision,
        idempotency_key=f"sched-commit-{run['id']}-{revision}",
    )
    try:
        result = service.commit_order(identity, body)
    except Problem as exc:
        if exc.code in TRANSIENT:
            raise
        with connection() as c:
            if exc.code == "PROPOSAL_EXPIRED":
                cancel_request(c, run["proposal_id"], run["buyer_id"], "run_retry", run["id"])
                c.execute(
                    """UPDATE scheduled_runs SET status='due',proposal_id=NULL,attempts=attempts+1,
                    lease_until=NULL,updated_at=%s WHERE id=%s""",
                    (now, run["id"]),
                )
                return run_event(c, run["id"], sched, "expired_prepare_again", {})
            auth_row = c.execute(
                "SELECT * FROM scheduled_authorizations WHERE id=%s FOR UPDATE", (auth["id"],)
            ).fetchone()
            return disrupt(c, run, auth_row, exc.code, {"codes": [exc.code], "lines": []}, now)
    with connection() as c:
        if result.get("status") != "revised":
            c.execute(
                """UPDATE scheduled_runs SET status='committed',order_id=%s,lease_until=NULL,
                updated_at=%s WHERE id=%s""",
                (result["order_id"], now, run["id"]),
            )
            return run_event(c, run["id"], sched, "committed", {"order_id": result["order_id"]})
        # The terms moved between prepare and commit: judge the new revision again.
        verdict = compare(
            auth,
            result["request"],
            result["snapshot"],
            result["policy_outcome"],
            run["substitutions"],
        )
        if verdict["ok"]:
            c.execute(
                "UPDATE scheduled_runs SET lease_until=NULL,updated_at=%s WHERE id=%s",
                (now, run["id"]),
            )
            return run_event(c, run["id"], sched, "revised", {"revision": result["revision"]})
        auth_row = c.execute(
            "SELECT * FROM scheduled_authorizations WHERE id=%s FOR UPDATE", (auth["id"],)
        ).fetchone()
        disrupt(c, run, auth_row, verdict["codes"][0], reason_of(verdict), now)


def scheduler_row(identity_id):
    with connection() as c:
        return c.execute("SELECT * FROM identities WHERE id=%s", (identity_id,)).fetchone()
