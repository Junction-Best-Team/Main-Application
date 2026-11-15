"""The customer's functions for scheduled (standing) re-orders. Orders placed from them are MOCKS.

Every write needs an approver (the human customer); the scheduler and agent identities are
refused. Prices and quantities never come from the client: a schedule is created from a past order
of the same buyer and from the exact terms the customer was just shown (`terms_fingerprint`).
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from aimo import scheduler
from aimo.approval_policy import can_approve, evaluate_purchase
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, js, now
from aimo.purchases import build_snapshot, context, load_products
from aimo.schedule_schemas import (
    ScheduleCreateRequest,
    ScheduleEditPreviewRequest,
    SchedulePreviewRequest,
    ScheduleReplaceRequest,
)
from aimo.schemas import PurchaseRequest

PAGE_OF_RUNS = 20
# Dates and the recipe link do not belong to a standing order; `constraints` is a server-only key of
# a stored request (the limits of that one purchase) and is not accepted by PrepareRequest.
REVIEWED_COUNT = "reviewed_ingredient_count_per_sales_unit"  # catalog.per_sales_for's basis
NOT_A_SCHEDULE_DATE = (
    "request_id",
    "delivery_date",
    "recipe_plan_id",
    "recipe_plan_revision",
    "constraints",
    "budget_gross",  # the one-off hard budget of that purchase; the standing order has its ceiling
)


def plain(value):
    """JSON-ready (dates as text) for error details; no web framework is imported here."""
    return json.loads(json.dumps(value, default=str))


def require_customer(identity):
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only the customer can manage a standing order.", 403)


def event(c, aid, actor, name, detail=None):
    c.execute(
        "INSERT INTO scheduled_authorization_events(authorization_id,actor_id,event,detail) "
        "VALUES(%s,%s,%s,%s)",
        (aid, actor, name, js(detail or {})),
    )


def pct(value):
    return f"{Decimal(str(value)):.2f}"


# --- the source order and the terms ---------------------------------------------------------


def source_order(c, identity, order_id):
    row = c.execute(
        """SELECT o.id,o.created_at,r.request,r.snapshot FROM orders o
        JOIN proposal_revisions r ON r.proposal_id=o.proposal_id AND r.revision=o.revision
        WHERE o.id=%s AND o.buyer_id=%s""",
        (order_id, identity["buyer_id"]),
    ).fetchone()
    if not row:
        raise Problem("NOT_FOUND", "Order not found.", 404)
    return row


def reorder_request(order):
    """The past order's lines and flags without dates, recipe link or declared substitutions.

    A recipe-backed prepare would attach to the already ordered proposal and a recipe request
    forbids per-line contributions, so a standing order is always a free-form basket."""
    request = {k: v for k, v in order["request"].items() if k not in NOT_A_SCHEDULE_DATE}
    resolved = {
        line["product_id"]: line["quantity"]
        for line in (order.get("snapshot") or {}).get("lines", [])
    }
    request["lines"] = [
        packs_if_counted(
            {k: v for k, v in line.items() if k != "substitutes_for"},
            resolved.get(line["product_id"]),
        )
        for line in request["lines"]
    ]
    return request


def packs_if_counted(line, quantity):
    """A count ("20 piece") converts to packs only through the reviewed recipe evidence bound to the
    recipe plan, which a free-form standing order does not carry. The customer's order already
    resolved it, so the reorder repeats those packs: their sales quantity in the sales unit."""
    if (
        quantity
        and REVIEWED_COUNT in (quantity.get("basis") or [])
        and quantity.get("sales_quantity")
        and quantity.get("sales_unit")
    ):
        return line | {"amount": str(quantity["sales_quantity"]), "unit": quantity["sales_unit"]}
    return line


def delivery_offset(order):
    placed = scheduler.helsinki_today(order["created_at"])
    asked = date.fromisoformat(str(order["request"]["delivery_date"]))
    return max(1, min(60, (asked - placed).days))


def check_line_rules(c, rules_in, request, scope, keep_known=False):
    """Per-ingredient accepted substitutes: real, not withdrawn, other than the line itself and
    inside the buyer's approved product scope (standing product authority, POL-004/POL-012)."""
    lines = {line["product_id"] for line in request["lines"]}
    rules = {}
    for product_id, rule in (rules_in or {}).items():
        if keep_known and product_id not in lines:
            continue  # carried over from the old schedule: it no longer has this product
        subs = list(dict.fromkeys(rule.accepted_substitutes))
        found = load_products(c, subs) if subs else {}
        if (
            product_id not in lines
            or any(s in lines or s == product_id for s in subs)
            or any(s not in found or found[s]["deleted"] for s in subs)
            or any(scope is None or s not in scope for s in subs)
        ):
            raise Problem("INVALID_LINE_RULE", "An accepted substitute is not allowed.", 422)
        rules[product_id] = {
            "accepted_substitutes": subs,
            "price_range_pct": pct(rule.price_range_pct),
        }
    return rules


def first_run_window():
    """Tomorrow to a year ahead (Q-103); demo mode (CNF-038) also allows today."""
    today = scheduler.helsinki_today()
    earliest = today if settings().scheduler_demo_mode else today + timedelta(days=1)
    return earliest, today + timedelta(days=365)


def build_terms(
    identity,
    service,
    order_id,
    recurrence,
    first_run_date,
    line_rules,
    title=None,
    keep_known=False,
):
    earliest, latest = first_run_window()
    if not earliest <= first_run_date <= latest:
        raise Problem(
            "INVALID_FIRST_RUN_DATE",
            f"The first run date must be between {earliest} and {latest}.",
            422,
        )
    rule = scheduler.normalize_recurrence(recurrence.model_dump(exclude_none=True))
    with connection() as c:
        context(c, identity)
        order = source_order(c, identity, order_id)
    offset = delivery_offset(order)
    valid_until = first_run_date + timedelta(days=365)
    dates = scheduler.next_dates(rule, first_run_date, valid_until, limit=5)
    if not dates:
        raise Problem("INVALID_RECURRENCE", "The pattern has no date in the year.", 422)
    request = reorder_request(order)
    probe = PurchaseRequest.model_validate(
        request
        | {"request_id": "standing-order", "delivery_date": dates[0] + timedelta(days=offset)}
    ).model_dump(mode="json")
    snapshot, _, _ = build_snapshot(
        identity, PurchaseRequest.model_validate(probe), service.connector
    )
    with connection() as c:
        _, policy, _, approvers = context(c, identity)
        scope = policy["rules"].get("approved_product_ids")
        rules = check_line_rules(c, line_rules, request, scope, keep_known)
        names = load_products(c, [s for r in rules.values() for s in r["accepted_substitutes"]])
    evaluated = evaluate_purchase(
        probe, snapshot, policy["rules"], [a["authority"] for a in approvers]
    )
    lines = [agreed_line(line, rules.get(line["product_id"]), names) for line in snapshot["lines"]]
    return {
        "source_order_id": str(order["id"]),
        "title": title
        or str(order["request"].get("request_id") or "").strip()[:80]
        or "Standing order",
        "lines": [{k: v for k, v in line.items() if k != "deposits"} for line in lines],
        "_agreed_lines": lines,  # with the deposit structure, stored for the run time check
        "currency": snapshot["currency"],
        "gross_total": snapshot["gross_total"],
        "policy_outcome": evaluated["policy_outcome"],
        "_required_exceptions": evaluated["required_exceptions"],
        "terms_fingerprint": scheduler.terms_fingerprint(probe, snapshot),
        "delivery_offset_days": offset,
        "recurrence": rule,
        "first_run_date": first_run_date,
        "valid_until": valid_until,
        "next_dates": dates,
        "blocking_reasons": [
            r
            for r in evaluated["reasons"]
            if r["severity"] in ("denied", "unresolved", "exception")
        ],
        "_request": request,
        "_rules": rules,
    }


def agreed_line(line, rule, names):
    evidence, quantity = line["commercial_evidence"], line["quantity"]
    return {
        "product_id": line["product_id"],
        "name": line["name"],
        "amount": quantity["requested_amount"],
        "unit": quantity["requested_unit"],
        "sales_quantity": quantity["sales_quantity"],
        "sales_unit": quantity["sales_unit"],
        "unit_net": evidence["net"],
        "unit_gross": evidence["gross"],
        "tax_rate": evidence["tax_rate"],
        "line_gross": line["gross"],
        "deposits": scheduler.deposit_structure(
            line["deposit_lines"]
        ),  # kept for the run time check
        "accepted_substitutes": [
            {
                "product_id": s,
                "name": names[s]["name"],
                "unit_gross": None,
                "sales_unit": names[s]["sales_unit"],
            }
            for s in (rule or {}).get("accepted_substitutes", [])
            if s in names
        ],
        "price_range_pct": (rule or {}).get("price_range_pct", "0.00"),
    }


def public_terms(terms):
    return {k: v for k, v in terms.items() if not k.startswith("_")}


def preview(identity, body: SchedulePreviewRequest, service):
    require_customer(identity)
    terms = build_terms(
        identity,
        service,
        body.order_id,
        body.recurrence,
        body.first_run_date,
        body.line_rules,
        body.title,
    )
    return public_terms(terms)


# --- reading --------------------------------------------------------------------------------


def run_summary(row):
    return {
        "id": str(row["id"]),
        "scheduled_date": row["scheduled_date"],
        "delivery_date": row["delivery_date"],
        "status": row["status"],
        "reason_code": row["reason_code"],
        "reason": row["reason"],
        "substitutions": row["substitutions"] or [],
        "proposal_id": str(row["proposal_id"]) if row["proposal_id"] else None,
        "order_id": str(row["order_id"]) if row["order_id"] else None,
        "conversation_id": str(row["conversation_id"]) if row["conversation_id"] else None,
        "updated_at": row["updated_at"],
    }


def response(c, row):
    last = c.execute(
        "SELECT * FROM scheduled_runs WHERE authorization_id=%s ORDER BY scheduled_date DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    chat = c.execute(
        """SELECT conversation_id FROM scheduled_runs WHERE authorization_id=%s
        AND conversation_id IS NOT NULL ORDER BY scheduled_date DESC LIMIT 1""",
        (row["id"],),
    ).fetchone()
    successor = c.execute(
        "SELECT id FROM scheduled_authorizations WHERE supersedes_id=%s ORDER BY created_at LIMIT 1",
        (row["id"],),
    ).fetchone()
    order = source_order_title(c, row["source_order_id"])
    rules = row["line_rules"] or {}
    names = load_products(c, [s for r in rules.values() for s in r.get("accepted_substitutes", [])])
    lines = [
        {
            k: v
            for k, v in line.items()
            if k not in ("accepted_substitutes", "price_range_pct", "deposits")
        }
        | {
            "accepted_substitutes": [
                {
                    "product_id": s,
                    "name": names[s]["name"],
                    "unit_gross": None,
                    "sales_unit": names[s]["sales_unit"],
                }
                for s in rules.get(line["product_id"], {}).get("accepted_substitutes", [])
                if s in names
            ],
            "price_range_pct": rules.get(line["product_id"], {}).get("price_range_pct", "0.00"),
        }
        for line in row["agreed_lines"]
    ]
    return {
        "id": str(row["id"]),
        "title": row["title"] or order,
        "status": row["status"],
        "stop_reason": row["stop_reason"],
        "source_order_id": str(row["source_order_id"]),
        "supersedes_id": str(row["supersedes_id"]) if row["supersedes_id"] else None,
        "replaced_by": str(successor["id"]) if successor else None,
        "recurrence": row["recurrence"],
        "first_run_date": row["first_run_date"],
        "valid_until": row["valid_until"],
        "next_run_date": row["next_run_date"],
        "paused_at": row["paused_at"],
        "delivery_offset_days": row["delivery_offset_days"],
        "currency": row["currency"],
        "agreed_gross_total": f"{row['agreed_gross_total']:.2f}",
        "price_ceiling_gross": f"{row['price_ceiling_gross']:.2f}",
        "lines": lines,
        "last_run": run_summary(last) if last else None,
        "conversation_id": str(chat["conversation_id"]) if chat else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def source_order_title(c, order_id):
    row = c.execute(
        """SELECT r.request->>'request_id' AS label FROM orders o
        JOIN proposal_revisions r ON r.proposal_id=o.proposal_id AND r.revision=o.revision
        WHERE o.id=%s""",
        (order_id,),
    ).fetchone()
    return (row and row["label"]) or "Standing order"


def owned(c, identity, schedule_id, lock=False):
    row = c.execute(
        "SELECT * FROM scheduled_authorizations WHERE id=%s AND buyer_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (schedule_id, identity["buyer_id"]),
    ).fetchone()
    if not row:
        raise Problem("NOT_FOUND", "Standing order not found.", 404)
    return row


STATUSES = ("active", "paused", "stopped", "cancelled", "expired", "superseded")


def list_schedules(identity, offset, limit, statuses=()):
    """The customer's schedules, newest first; `statuses` filters before paging (empty: all)."""
    wanted = list(dict.fromkeys(statuses))
    if any(item not in STATUSES for item in wanted):
        raise Problem(
            "INVALID_SCHEDULE_STATUS", f"Status must be one of {', '.join(STATUSES)}.", 422
        )
    with connection() as c:
        context(c, identity)
        rows = c.execute(
            """SELECT * FROM scheduled_authorizations WHERE buyer_id=%s
            AND (cardinality(%s::text[])=0 OR status=ANY(%s::text[]))
            ORDER BY created_at DESC,id LIMIT %s OFFSET %s""",
            (identity["buyer_id"], wanted, wanted, limit + 1, offset),
        ).fetchall()
        return {
            "items": [response(c, r) for r in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None,
        }


def get(identity, schedule_id, runs_offset=0):
    with connection() as c:
        context(c, identity)
        row = owned(c, identity, schedule_id)
        runs = c.execute(
            """SELECT * FROM scheduled_runs WHERE authorization_id=%s
            ORDER BY scheduled_date DESC LIMIT %s OFFSET %s""",
            (row["id"], PAGE_OF_RUNS + 1, runs_offset),
        ).fetchall()
        return response(c, row) | {
            "runs": [run_summary(r) for r in runs[:PAGE_OF_RUNS]],
            "runs_next_offset": runs_offset + PAGE_OF_RUNS if len(runs) > PAGE_OF_RUNS else None,
        }


# --- writing --------------------------------------------------------------------------------


def lock_buyer(c, identity):
    c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (identity["buyer_id"],))


def insert(c, identity, terms, *, key, digest, ceiling, supersedes=None):
    """Insert one authorization under the buyer lock; the limit and the key are checked here."""
    old = c.execute(
        "SELECT * FROM scheduled_authorizations WHERE buyer_id=%s AND create_key=%s",
        (identity["buyer_id"], key),
    ).fetchone()
    if old:
        if old["create_hash"] != digest:
            raise Problem("IDEMPOTENCY_CONFLICT", "This key already identifies another schedule.")
        return old
    active = c.execute(
        """SELECT count(*) AS n FROM scheduled_authorizations
        WHERE buyer_id=%s AND status IN ('active','paused')""",
        (identity["buyer_id"],),
    ).fetchone()["n"]
    if active >= settings().scheduler_max_active_schedules:
        raise Problem("SCHEDULE_LIMIT", "Too many active standing orders; cancel one first.", 429)
    if Decimal(str(ceiling)) < Decimal(terms["gross_total"]):
        raise Problem(
            "SCHEDULE_CEILING_TOO_LOW", "The price ceiling is below the agreed total.", 422
        )
    aid = uuid4()
    row = c.execute(
        """INSERT INTO scheduled_authorizations(id,buyer_id,created_by,source_order_id,supersedes_id,
        create_key,create_hash,title,request,line_rules,agreed_lines,terms_fingerprint,currency,
        agreed_gross_total,price_ceiling_gross,delivery_offset_days,recurrence,first_run_date,
        valid_until,next_run_date) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING *""",
        (
            aid,
            identity["buyer_id"],
            identity["id"],
            UUID(terms["source_order_id"]),
            supersedes,
            key,
            digest,
            terms["title"],
            js(terms["_request"]),
            js(terms["_rules"]),
            js(terms["_agreed_lines"]),
            terms["terms_fingerprint"],
            terms["currency"],
            terms["gross_total"],
            ceiling,
            terms["delivery_offset_days"],
            js(terms["recurrence"]),
            terms["first_run_date"],
            terms["valid_until"],
            terms["next_dates"][0],
        ),
    ).fetchone()
    event(
        c, aid, identity["id"], "created", {"supersedes": str(supersedes) if supersedes else None}
    )
    return row


def require_authority(identity, terms, ceiling):
    """The creating approver authorizes every run up to the ceiling, so their own limit and
    exceptions must cover the larger of the agreed total and the ceiling (as `confirm` does for a
    single purchase): the demo policy only needs ANY approver to cover a total, not this one."""
    total = max(Decimal(terms["gross_total"]), Decimal(str(ceiling)))
    if not can_approve(
        identity["authority"], total, terms["currency"], terms["_required_exceptions"]
    ):
        raise Problem(
            "APPROVAL_SCOPE",
            "This amount or exception exceeds your current authority to approve.",
            403,
        )


def agree(terms, agreed_fingerprint):
    if terms["policy_outcome"] != "ready_to_commit":
        raise Problem(
            "SCHEDULE_NOT_REORDERABLE",
            "This order needs a decision each time and cannot be scheduled as it is.",
            422,
            details=plain({"blocking_reasons": terms["blocking_reasons"]}),
        )
    if terms["terms_fingerprint"] != agreed_fingerprint:
        raise Problem(
            "SCHEDULE_TERMS_CHANGED",
            "Prices or products changed; review the new terms.",
            409,
            details=plain({"terms": public_terms(terms)}),
        )


def stored_by_key(identity, key, digest):
    """The schedule an earlier request with this key created, found before any supplier lookup."""
    with connection() as c:
        context(c, identity)
        row = c.execute(
            "SELECT * FROM scheduled_authorizations WHERE buyer_id=%s AND create_key=%s",
            (identity["buyer_id"], key),
        ).fetchone()
        if not row:
            return None
        if row["create_hash"] != digest:
            raise Problem("IDEMPOTENCY_CONFLICT", "This key already identifies another schedule.")
        return response(c, row)


def create(identity, body: ScheduleCreateRequest, service):
    require_customer(identity)
    digest = fingerprint(body.model_dump(mode="json", exclude={"idempotency_key"}))
    again = stored_by_key(identity, body.idempotency_key, digest)
    if again:  # a retry never calls the supplier again
        return again
    terms = build_terms(
        identity,
        service,
        body.order_id,
        body.recurrence,
        body.first_run_date,
        body.line_rules,
        body.title,
    )
    agree(terms, body.agreed_terms_fingerprint)
    require_authority(identity, terms, body.price_ceiling_gross)
    with connection() as c:
        context(c, identity, lock=True)
        lock_buyer(c, identity)
        row = insert(
            c,
            identity,
            terms,
            key=body.idempotency_key,
            digest=digest,
            ceiling=body.price_ceiling_gross,
        )
        return response(c, row)


def edited(old, body):
    """The terms of a replacement: whatever the customer changed, the old schedule otherwise."""
    from aimo.schedule_schemas import LineRule, Recurrence

    earliest = first_run_window()[0]
    rules = body.line_rules
    if rules is None:
        rules = {k: LineRule.model_validate(v) for k, v in (old["line_rules"] or {}).items()}
    return {
        "order_id": body.source_order_id or old["source_order_id"],
        "recurrence": body.recurrence or Recurrence.model_validate(old["recurrence"]),
        "first_run_date": body.first_run_date or max(earliest, old["next_run_date"] or earliest),
        "line_rules": rules,
        "title": body.title or old["title"],
        "keep_known": body.line_rules is None,  # carried-over rules only where they still apply
    }


def preview_edit(identity, schedule_id, body: ScheduleEditPreviewRequest, service):
    require_customer(identity)
    with connection() as c:
        context(c, identity)
        old = owned(c, identity, schedule_id)
    return public_terms(build_terms(identity, service, **edited(old, body)))


def replace(identity, schedule_id, body: ScheduleReplaceRequest, service):
    """Edit or restart: a new authorization with fresh agreed prices supersedes the old one."""
    require_customer(identity)
    digest_of = lambda old_id: fingerprint(  # noqa: E731
        body.model_dump(mode="json", exclude={"idempotency_key"}) | {"replaces": str(old_id)}
    )
    with connection() as c:
        context(c, identity)
        old = owned(c, identity, schedule_id)
        again = c.execute(
            "SELECT * FROM scheduled_authorizations WHERE buyer_id=%s AND create_key=%s",
            (identity["buyer_id"], body.idempotency_key),
        ).fetchone()
        if again:  # a repeated request answers before anything else is looked at
            if again["create_hash"] != digest_of(old["id"]):
                raise Problem(
                    "IDEMPOTENCY_CONFLICT", "This key already identifies another schedule."
                )
            return response(c, again)
    if old["status"] not in ("active", "paused", "stopped"):
        raise Problem("SCHEDULE_NOT_ACTIVE", "This standing order is finished.", 409)
    terms = build_terms(identity, service, **edited(old, body))
    agree(terms, body.agreed_terms_fingerprint)
    digest = digest_of(old["id"])
    ceiling = (
        body.price_ceiling_gross
        if body.price_ceiling_gross is not None
        else old["price_ceiling_gross"]
    )
    require_authority(identity, terms, ceiling)
    with connection() as c:
        context(c, identity, lock=True)
        lock_buyer(c, identity)
        old = owned(c, identity, schedule_id, lock=True)
        # Under the locks the first look is stale: a cancel, a pause or another replace may have
        # landed since. One winner: a schedule that is finished or already has a successor is refused.
        again = c.execute(
            "SELECT 1 FROM scheduled_authorizations WHERE buyer_id=%s AND create_key=%s",
            (identity["buyer_id"], body.idempotency_key),
        ).fetchone()
        successor = c.execute(
            "SELECT 1 FROM scheduled_authorizations WHERE supersedes_id=%s", (old["id"],)
        ).fetchone()
        if not again and (old["status"] not in ("active", "paused", "stopped") or successor):
            raise Problem("SCHEDULE_NOT_ACTIVE", "This standing order was already changed.", 409)
        was_paused = old["status"] == "paused"
        if old["status"] in ("active", "paused"):
            c.execute(
                "UPDATE scheduled_authorizations SET status='superseded',next_run_date=NULL,"
                "paused_at=NULL,updated_at=%s WHERE id=%s",
                (now(), old["id"]),
            )
            event(c, old["id"], identity["id"], "superseded", {})
        row = insert(
            c,
            identity,
            terms,
            key=body.idempotency_key,
            digest=digest,
            ceiling=ceiling,
            supersedes=old["id"],
        )
        if was_paused and row["status"] == "active":
            # A paused schedule that is edited stays paused (a holiday is not ended by a rename).
            stamp = now()
            row = c.execute(
                "UPDATE scheduled_authorizations SET status='paused',paused_at=%s,updated_at=%s "
                "WHERE id=%s RETURNING *",
                (stamp, stamp, row["id"]),
            ).fetchone()
            event(c, row["id"], identity["id"], "paused", {"by": "replace of a paused schedule"})
        return response(c, row)


def move(identity, schedule_id, event_name, wanted, *, allowed_from):
    """One status move of the customer's own schedule; repeating it is harmless."""
    require_customer(identity)
    with connection() as c:
        context(c, identity, lock=True)
        row = owned(c, identity, schedule_id, lock=True)
        if row["status"] == wanted:
            return response(c, row)
        if row["status"] not in allowed_from:
            raise Problem(
                "SCHEDULE_NOT_ACTIVE", f"A {row['status']} standing order cannot be changed.", 409
            )
        if wanted == "active" and row["valid_until"] < scheduler.helsinki_today():
            c.execute(
                "UPDATE scheduled_authorizations SET status='expired',next_run_date=NULL,"
                "paused_at=NULL,updated_at=%s WHERE id=%s",
                (now(), row["id"]),
            )
            event(c, row["id"], identity["id"], "expired", {})
            c.connection.commit()
            raise Problem("SCHEDULE_NOT_ACTIVE", "The year of this standing order is over.", 409)
        stamp = now()
        if wanted == "active":
            # Resume continues from the next date (Q-90): the paused dates up to today become
            # skipped runs now, so a worker that was down meanwhile cannot call them missed.
            scheduler.open_dates(c, row, scheduler.helsinki_today(), True, stamp)
        row = c.execute(
            """UPDATE scheduled_authorizations SET status=%s,updated_at=%s,
            paused_at=%s,next_run_date=CASE WHEN %s IN ('cancelled') THEN NULL ELSE next_run_date END
            WHERE id=%s RETURNING *""",
            (wanted, stamp, stamp if wanted == "paused" else None, wanted, row["id"]),
        ).fetchone()
        if wanted == "cancelled":
            # The run's open proposal must not stay confirmable after the cancel (the customer's own
            # explicit confirm of it would still be valid otherwise).
            for open_run in c.execute(
                "SELECT * FROM scheduled_runs WHERE authorization_id=%s AND status='prepared' "
                "AND proposal_id IS NOT NULL",
                (row["id"],),
            ).fetchall():
                scheduler.cancel_request(
                    c,
                    open_run["proposal_id"],
                    open_run["buyer_id"],
                    "customer_cancelled",
                    open_run["id"],
                )
        event(c, row["id"], identity["id"], event_name, {})
        return response(c, row)


def cancel(identity, schedule_id):
    return move(
        identity,
        schedule_id,
        "cancelled",
        "cancelled",
        allowed_from=("active", "paused", "stopped"),
    )


def pause(identity, schedule_id):
    return move(identity, schedule_id, "paused", "paused", allowed_from=("active",))


def resume(identity, schedule_id):
    return move(identity, schedule_id, "resumed", "active", allowed_from=("paused",))


def substitute_candidates(identity, product_id, service):
    """Catalog substitutes the browser may offer in the dropdown: inside the approved scope."""
    require_customer(identity)
    if "\x00" in product_id or len(product_id) > 40:
        raise Problem("INVALID_PRODUCT_ID", "That is not a product id.", 422)
    found = service.list_substitution_candidates(identity, product_id)
    with connection() as c:
        _, policy, _, _ = context(c, identity)
    scope = policy["rules"].get("approved_product_ids") or []
    return {
        "product_id": product_id,
        "candidates": [
            {
                "product_id": item["id"],
                "name": item["name"],
                "unit_gross": None,
                "sales_unit": item.get("sales_unit"),
            }
            for item in found["candidates"]
            if item["id"] in scope
        ],
    }


def run_now(identity, schedule_id, service):
    """DEMO ONLY (CNF-038): make the schedule's run for today due at once. The worker then executes
    it through the same engine and the same checks; nothing is skipped and nothing runs inline."""
    require_customer(identity)
    if not settings().scheduler_demo_mode:
        raise Problem("SCHEDULE_DEMO_DISABLED", "The demo trigger is switched off.", 403)
    with connection() as c:
        context(c, identity, lock=True)
        row = owned(c, identity, schedule_id, lock=True)
        if row["status"] != "active" or row["valid_until"] < scheduler.helsinki_today():
            raise Problem("SCHEDULE_NOT_ACTIVE", "Only an active standing order can run now.", 409)
        scheduler.open_demo_run(c, row, now())
        return response(c, row)
