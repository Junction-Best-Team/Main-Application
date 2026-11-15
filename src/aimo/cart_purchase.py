"""Prepare the order straight from the conversation's cart, without the assistant.

The cart on screen is display only. This module never reads it: it takes the conversation's latest
stored meal plan (or, for a saved recipe plan, reloads that plan from the server), reads every matched
product again from the catalog, and then uses the ordinary ``ToolSession.prepare`` (combine and check
the lines, fresh supplier price and stock, policy, ceiling, the customer's stated limits). The result
is the normal proposal. It authorizes nothing: the customer still confirms the exact revision.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from pydantic import ValidationError

from aimo import approval_workflow as workflow
from aimo import auth, scheduler
from aimo.agent_tools import PrepareOrderInput, ToolSession
from aimo.chat_schemas import CartNotIncluded, MealPlan
from aimo.config import settings
from aimo.conversations import customer_constraints, owned
from aimo.db import Problem, connection, fingerprint, now
from aimo.observability import event
from aimo.purchases import context
from aimo.schemas import LineRequest, Requirements


def positive(amount):
    try:
        return amount is not None and Decimal(amount).is_finite() and Decimal(amount) > 0
    except InvalidOperation:
        return False


def split_plain(plan):
    """(bought, not_included): an item needs a product and a quantity and a unit to be bought."""
    bought, left_out = [], []
    for item in plan.ingredients:
        if item.amount is not None and not positive(item.amount):
            raise Problem("CART_NOT_VERIFIED", "The cart could not be verified.", 422)
        if not item.product_id:
            reason = "no_product"
        elif item.amount is None or not item.unit.strip():
            reason = "no_quantity"
        else:
            bought.append(item)
            continue
        left_out.append(
            CartNotIncluded(name=item.name, amount=item.amount, unit=item.unit, reason=reason)
        )
    return bought, left_out


def requirements_from(limits):
    """The customer's dietary limits, so the request never looks looser than what they said."""
    on = {c["name"] for c in limits if c["value"] is True}
    return Requirements(
        lactose_free="lactose_free" in on,
        milk_free="milk_free" in on,
        unsupported=[
            n.removeprefix("unsupported:") for n in sorted(on) if n.startswith("unsupported:")
        ],
    )


def lines_of(items, recipe):
    """One line per (product, unit); amounts of ingredients that share a product are summed."""
    sums = {}
    for item in items:
        amount = item.purchase_amount if recipe else item.amount
        unit = item.purchase_unit if recipe else item.unit
        key = (item.product_id, unit)
        sums[key] = sums.get(key, Decimal(0)) + Decimal(amount)
    return [
        LineRequest(product_id=pid, amount=format(total.normalize(), "f"), unit=unit)
        for (pid, unit), total in sums.items()
    ]


def cart_plan(messages):
    """The conversation's cart plan: the latest stored one (a basket for it may already exist: a new
    press makes a revised basket and the older open one is cancelled)."""
    at = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]["meal_plan"]), None)
    if at is None:
        raise Problem("EMPTY_CART", "There is nothing in the cart to buy yet.", 422)
    return messages[at]["meal_plan"]


def answer(identity, pid, left_out):
    return {
        "proposal": workflow.get_proposal(identity, pid),
        "not_included": [item.model_dump() for item in left_out],
    }


def left_out_for_replay(plan_data):
    try:
        plan = MealPlan.model_validate(plan_data)
    except ValidationError:
        return []
    return [] if plan.recipe_plan_id else split_plain(plan)[1]


def prepare_basket(identity, cid, stored, delivery_date, destination, key, limits, service, tid):
    """Prepare a basket for one stored plan. In the same transaction that creates it, the
    conversation's other unconfirmed baskets are cancelled (never one with an order).
    Returns (proposal_id, not_included, notice)."""
    actor = auth.internal_agent(identity) | {"_turn_id": str(tid)}
    session = ToolSession(actor, service, constraints=limits or None)
    session.preparation_key = key
    session.supersede = {"conversation_id": str(cid), "by": identity["id"]}
    recipe = bool(isinstance(stored, dict) and stored.get("recipe_plan_id"))
    left_out = []
    if recipe:
        # The saved plan is reloaded by the server; the message only points at it. A saved recipe
        # plan must be fully matched to be prepared (the existing rule): nothing is left out here.
        try:
            plan_id = UUID(str(stored["recipe_plan_id"]))
        except ValueError:
            raise Problem("CART_NOT_VERIFIED", "The cart could not be verified.", 422) from None
        if not session.restore_saved_plan(plan_id):
            raise Problem("CART_NOT_VERIFIED", "The cart could not be verified.", 422)
        open_items = [
            i.name for i in session.plan.ingredients if i.status != "matched" or not i.product_id
        ]
        if open_items:
            raise Problem(
                "CART_INCOMPLETE",
                "Every ingredient of a saved recipe must have a product before it can be bought.",
                422,
                details={"unmatched": open_items},
            )
        items = session.plan.ingredients
    else:
        try:
            plan = MealPlan.model_validate(stored)
        except ValidationError:
            raise Problem("CART_NOT_VERIFIED", "The cart could not be verified.", 422) from None
        items, left_out = split_plain(plan)
        if not items:
            raise Problem(
                "EMPTY_CART", "No item in the cart has a product and a quantity yet.", 422
            )
        if not session.restore_plan(
            plan.model_copy(update={"ingredients": items}).model_dump(mode="json")
        ):
            raise Problem("CART_NOT_VERIFIED", "The cart could not be verified.", 422)
    request = PrepareOrderInput(
        request_id=("Cart: " + session.plan.title)[:100],
        destination=destination,
        delivery_date=delivery_date,
        requirements=requirements_from(limits),
        lines=lines_of(items, recipe),
    )
    proposal = session.prepare(request)
    notice = session.result("", include_plan=False).text
    if left_out:
        notice += "\n\nNot included: " + ", ".join(i.name for i in left_out) + "."
    return proposal["proposal_id"], left_out, notice


def prepare_from_cart(identity, cid, body, service):
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only a buyer session can prepare a purchase.", 403)
    digest = fingerprint(
        {"delivery_date": str(body.delivery_date), "destination": body.destination}
    )
    with connection() as c:
        context(c, identity)
        owned(c, identity, cid)
        old = c.execute(
            "SELECT id,payload_hash FROM conversation_turns WHERE conversation_id=%s AND key=%s",
            (cid, body.request_id),
        ).fetchone()
        messages = c.execute(
            """SELECT id,role,meal_plan,proposal_id,turn_id FROM conversation_messages
            WHERE conversation_id=%s AND notice IS NULL ORDER BY id""",
            (cid,),
        ).fetchall()
        if old:
            if old["payload_hash"] != digest:
                raise Problem(
                    "IDEMPOTENCY_CONFLICT", "This key already identifies another purchase request."
                )
            made = next(
                (m for m in messages if m["turn_id"] == old["id"] and m["proposal_id"]), None
            )
            if made:  # replay: the same proposal, the same list of what was left out
                before = [m for m in messages if m["id"] < made["id"] and m["meal_plan"]]
                return answer(
                    identity,
                    made["proposal_id"],
                    left_out_for_replay(before[-1]["meal_plan"]) if before else [],
                )
        unfinished = c.execute(
            "SELECT state FROM conversation_turns WHERE conversation_id=%s AND state!='complete'",
            (cid,),
        ).fetchone()
        if unfinished:
            raise Problem(
                "CONVERSATION_BUSY"
                if unfinished["state"] != "failed"
                else "RETRY_PREVIOUS_MESSAGE",
                "A response is in progress."
                if unfinished["state"] != "failed"
                else "Retry the previous message first.",
                409,
                3,
            )
        limits = customer_constraints(c, cid)
    stored = cart_plan(messages)
    tid = uuid4()
    key = "cart-" + fingerprint({"conversation": str(cid), "key": body.request_id})
    pid, left_out, notice = prepare_basket(
        identity, cid, stored, body.delivery_date, body.destination, key, limits, service, tid
    )
    summary = "Prepared from my cart for " + f"{body.delivery_date} to {body.destination}."
    with connection() as c:
        owned(c, identity, cid, lock=True)
        busy = c.execute(
            "SELECT 1 FROM conversation_turns WHERE conversation_id=%s AND state!='complete'",
            (cid,),
        ).fetchone()
        if busy:
            raise Problem("CONVERSATION_BUSY", "A response is in progress.", 409, 3)
        made = c.execute(
            """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
            attempt,requested_by,worker_attempts,submitted_by)
            VALUES(%s,%s,%s,%s,'complete',%s,%s,%s,0,%s) ON CONFLICT(conversation_id,key) DO NOTHING
            RETURNING id""",
            (tid, cid, body.request_id, digest, now(), uuid4(), identity["id"], identity["id"]),
        ).fetchone()
        if made:  # a concurrent identical press already wrote the pair; the proposal is the same
            c.execute(
                "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'user',%s)",
                (cid, tid, summary),
            )
            c.execute(
                """INSERT INTO conversation_messages(conversation_id,turn_id,role,text,proposal_id)
                VALUES(%s,%s,'assistant',%s,%s)""",
                (cid, tid, notice, pid),
            )
            c.execute("UPDATE conversations SET updated_at=%s WHERE id=%s", (now(), cid))
    return answer(identity, pid, left_out)


# --- the always-finalized cart: prepare after a chat turn that changed the plan -----------------------


def latest_terms(c, cid):
    """The newest basket of the conversation (the model's or the cart's) and its request."""
    return c.execute(
        """SELECT p.id, q.request FROM conversation_messages m
        JOIN proposals p ON p.id=m.proposal_id
        JOIN proposal_revisions q ON q.proposal_id=p.id AND q.revision=p.current_revision
        WHERE m.conversation_id=%s ORDER BY m.id DESC LIMIT 1""",
        (cid,),
    ).fetchone()


def terms_for(latest, policy):
    """Delivery date and destination of the latest basket, else tomorrow (Helsinki) and the first
    destination of the buyer's policy. A date that has passed falls back to tomorrow."""
    tomorrow = scheduler.helsinki_today() + timedelta(days=1)
    if latest:
        try:
            when = date.fromisoformat(latest["request"]["delivery_date"])
        except (KeyError, ValueError, TypeError):
            when = tomorrow
        return max(when, tomorrow), latest["request"]["destination"]
    return tomorrow, (policy["rules"].get("destinations") or ["hotel-helsinki"])[0]


def same_basket(latest, lines, when, destination):
    """True if the latest basket already holds exactly these lines for these terms."""
    if not latest:
        return False
    request = latest["request"]
    mine = sorted((line.product_id, Decimal(line.amount), line.unit) for line in lines)
    theirs = sorted(
        (line["product_id"], Decimal(line["amount"]), line["unit"]) for line in request["lines"]
    )
    return (
        mine == theirs
        and request["delivery_date"] == str(when)
        and request["destination"] == destination
    )


def auto_prepare(identity, cid, tid, result, service):
    """After a customer's chat turn that left a changed cart, prepare the basket from it.

    Never raises: an empty or incomplete cart is simply not prepared; any failure is logged and the
    customer keeps the last good basket. Server-originated, so the model-level semantic prepare check
    does not run; every fixed rule (policy, ceiling, the customer's stated limits, evidence) does.
    Returns (proposal_id, not_included, notice) or None."""
    if not settings().cart_auto_prepare or result.proposal_id or not result.meal_plan:
        return None
    stored = result.meal_plan.model_dump(mode="json")
    try:
        with connection() as c:
            _, policy, _, _ = context(c, identity)
            limits = customer_constraints(c, cid, tid)
            latest = latest_terms(c, cid)
        when, destination = terms_for(latest, policy)
        if not stored.get("recipe_plan_id"):
            plan = MealPlan.model_validate(stored)
            items, _ = split_plain(plan)
            if items and same_basket(latest, lines_of(items, False), when, destination):
                return None  # nothing changed: no new revision
        key = "auto-" + fingerprint(
            {
                "conversation": str(cid),
                "plan": stored,
                "terms": [str(when), destination],
                "limits": limits,
                "after": str(latest["id"]) if latest else None,
            }
        )
        pid, left_out, notice = prepare_basket(
            identity, cid, stored, when, destination, key, limits, service, tid
        )
    except Problem as exc:
        if exc.code not in ("EMPTY_CART", "CART_INCOMPLETE"):
            event("cart.auto_prepare_failed", error_code=exc.code, conversation_id=str(cid))
        return None
    except Exception as exc:  # a display convenience: it must never fail the customer's turn
        event("cart.auto_prepare_failed", error_code=type(exc).__name__, conversation_id=str(cid))
        return None
    if latest and str(latest["id"]) == str(pid):
        return None
    return pid, left_out, notice
