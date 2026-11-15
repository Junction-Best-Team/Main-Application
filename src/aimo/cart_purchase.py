"""Prepare the order straight from the conversation's cart, without the assistant.

The cart on screen is display only. This module never reads it: it takes the conversation's latest
stored meal plan (or, for a saved recipe plan, reloads that plan from the server), reads every matched
product again from the catalog, and then uses the ordinary ``ToolSession.prepare`` (combine and check
the lines, fresh supplier price and stock, policy, ceiling, the customer's stated limits). The result
is the normal proposal. It authorizes nothing: the customer still confirms the exact revision.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import floor
from uuid import UUID, uuid4

from pydantic import ValidationError

from aimo import approval_workflow as workflow
from aimo import auth, catalog, request_brief, scheduler
from aimo.agent_stop import cart_label
from aimo.agent_tools import PrepareOrderInput, ToolSession, is_zero
from aimo.chat_schemas import CartNotIncluded, CartPurchaseRequest, MealPlan
from aimo.config import settings
from aimo.conversations import RECIPE_LOCKED_REASON, customer_constraints, owned
from aimo.db import Problem, connection, fingerprint, js, now
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
        if item.amount is not None and is_zero(item.amount):
            reason = "removed"  # the customer set it to 0 on the card: kept in the cart, not bought
            left_out.append(
                CartNotIncluded(name=item.name, amount=item.amount, unit=item.unit, reason=reason)
            )
            continue
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


def not_included_now(messages, purchases):
    """The items the CURRENT basket leaves out, for the card after a reload (Q-124 a).

    Computed from the latest stored plan, never stored: [] unless the newest basket is open (not
    cancelled, no order) and no newer plan was stored after it. A saved recipe plan has none (it must
    be fully matched); an unreadable plan has none."""
    plan_at = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]["meal_plan"]), None)
    basket_at = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i]["proposal_id"]), None
    )
    if plan_at is None or basket_at is None or plan_at > basket_at:
        return []
    basket = next(
        (p for p in purchases if p["proposal_id"] == str(messages[basket_at]["proposal_id"])), None
    )
    if not basket or basket["order_id"] or basket["approval_status"] == "cancelled":
        return []
    return left_out_for_replay(messages[plan_at]["meal_plan"])


def left_out_for_replay(plan_data):
    try:
        plan = MealPlan.model_validate(plan_data)
        return [] if plan.recipe_plan_id else split_plain(plan)[1]
    except (ValidationError, Problem):  # an unreadable stored plan lists nothing; reads never fail
        return []


def not_included_text(left_out):
    """The trusted note about items left out of the basket."""
    names = [i.name for i in left_out]
    return ("\n\nNot included: " + ", ".join(names) + ".") if names else ""


def read_basis(c, cid):
    """What a caller built its basket on: the newest stored plan and the newest basket link."""
    row = c.execute(
        """SELECT max(id) FILTER (WHERE meal_plan IS NOT NULL) AS plan_at,
        max(id) FILTER (WHERE proposal_id IS NOT NULL) AS basket_at
        FROM conversation_messages WHERE conversation_id=%s""",
        (cid,),
    ).fetchone()
    return row["plan_at"], row["basket_at"]


def basis_of(messages):
    plan_at = max((m["id"] for m in messages if m["meal_plan"]), default=None)
    basket_at = max((m["id"] for m in messages if m["proposal_id"]), default=None)
    return plan_at, basket_at


def prepare_basket(
    identity, cid, stored, delivery_date, destination, key, limits, service, tid, link
):
    """Prepare a basket for one stored plan. The supplier lookups happen first, without a lock; then,
    in ONE transaction under the buyer lock, the basket is created, the conversation's other
    unconfirmed baskets are cancelled (never one with an order) and (when `link` has `write`) the
    customer line and the assistant line that carries the basket are stored. Inside that transaction
    the conversation is locked and these are checked again: no turn in progress (`check_busy`), the
    plan the caller read is still the latest (`basis`: else CART_CHANGED) and the cart was not ordered
    meanwhile (`check_ordered`). Returns (proposal_id, not_included, notice)."""
    actor = auth.internal_agent(identity) | {"_turn_id": str(tid)}
    session = ToolSession(actor, service, constraints=limits or None)
    with connection() as c:
        brief = request_brief.load(c, cid)
    if brief:
        session.brief = brief
    session.preparation_key = key
    left_out_box = []

    def before(c):
        owned(c, identity, cid, lock=True)
        if link.get("check_busy"):
            busy = c.execute(
                "SELECT 1 FROM conversation_turns WHERE conversation_id=%s AND state!='complete'",
                (cid,),
            ).fetchone()
            if busy:
                raise Problem("CONVERSATION_BUSY", "A response is in progress.", 409, 3)
        if link.get("require_expired"):
            # A refresh only replaces an expired basket. Checked here, under the conversation lock,
            # so of several refreshes at once only the first prepares and the rest are refused.
            latest = latest_terms(c, cid)
            if not latest or not workflow.is_expired(c, identity, latest["id"]):
                raise Problem("BASKET_NOT_EXPIRED", "This basket has not expired.", 409)
        if link.get("basis") is not None and read_basis(c, cid) != link["basis"]:
            raise Problem(
                "CART_CHANGED", "The cart changed while the basket was prepared. Try again.", 409
            )
        if link.get("check_ordered"):
            refuse_if_ordered(c, cid)

    def after(c, pid, rendered):
        write = link.get("write")
        if not write:
            return
        session.proposal = rendered
        text = session.result("", include_plan=False).text + not_included_text(left_out_box)
        made = c.execute(
            """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
            attempt,requested_by,worker_attempts,submitted_by)
            VALUES(%s,%s,%s,%s,'complete',%s,%s,%s,0,%s) ON CONFLICT(conversation_id,key) DO NOTHING
            RETURNING id""",
            (
                tid,
                cid,
                write["key"],
                write["digest"],
                now(),
                uuid4(),
                identity["id"],
                identity["id"],
            ),
        ).fetchone()
        if made:
            c.execute(
                "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'user',%s)",
                (cid, tid, write["summary"]),
            )
            c.execute(
                """INSERT INTO conversation_messages(conversation_id,turn_id,role,text,meal_plan,proposal_id)
                VALUES(%s,%s,'assistant',%s,%s,%s)""",
                (cid, tid, text, js(write.get("plan")) if write.get("plan") else None, pid),
            )
            c.execute("UPDATE conversations SET updated_at=%s WHERE id=%s", (now(), cid))

    session.supersede = {
        "conversation_id": str(cid),
        "by": identity["id"],
        "before": before,
        "after": after,
    }
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
    left_out_box.extend(left_out)
    request = PrepareOrderInput(
        request_id=cart_label(session.plan.title),
        destination=destination,
        delivery_date=delivery_date,
        requirements=requirements_from(limits),
        lines=lines_of(items, recipe),
    )
    proposal = session.prepare(request)
    # A background success updates the card without appending a checkout script to
    # the recipe reply. Blockers and omitted ingredients must still be visible.
    notice = session.purchase_notice(include_ready=False) + not_included_text(left_out)
    return proposal["proposal_id"], left_out, notice


def replay_of(identity, old, messages, digest):
    """The same answer for a retried press or edit; a different body under the same key conflicts."""
    if not old:
        return None
    if old["payload_hash"] != digest:
        raise Problem("IDEMPOTENCY_CONFLICT", "This key already identifies another request.")
    made = next((m for m in messages if m["turn_id"] == old["id"] and m["proposal_id"]), None)
    if not made:
        return None
    before = [m for m in messages if m["id"] < made["id"] and m["meal_plan"]]
    plan_data = made["meal_plan"] or (before[-1]["meal_plan"] if before else None)
    return answer(
        identity, made["proposal_id"], left_out_for_replay(plan_data) if plan_data else []
    )


def retrying(attempt, tries=3):
    """Run an operation again from a fresh read when the cart changed under it (CART_CHANGED)."""
    for n in range(tries):
        try:
            return attempt()
        except Problem as exc:
            if exc.code != "CART_CHANGED" or n == tries - 1:
                raise


def prepare_from_cart(identity, cid, body, service, summary=None, require_expired=False):
    return retrying(
        lambda: prepare_from_cart_once(identity, cid, body, service, summary, require_expired)
    )


def refresh_basket(identity, cid, body, service):
    """Q-134 c: prepare an EXPIRED basket again from the customer's current cart.

    The cart is the stored plan (it holds the customer's own pack counts), so amounts are never
    changed here; the date and destination are the expired basket's (a date that has since passed
    falls back to tomorrow, as everywhere). The supplier is asked again for price and stock and every
    purchasing check runs as usual. Nothing is confirmed or ordered. A retry with the same
    request_id gets the same basket."""
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only a buyer session can prepare a purchase.", 403)
    with connection() as c:
        _, policy, _, _ = context(c, identity)
        owned(c, identity, cid)
        retried = c.execute(
            "SELECT 1 FROM conversation_turns WHERE conversation_id=%s AND key=%s",
            (cid, body.request_id),
        ).fetchone()
        refuse_if_ordered(c, cid)
        latest = latest_terms(c, cid)
    if not retried:
        if not latest:
            raise Problem(
                "NO_BASKET_TO_REFRESH", "There is no basket to refresh. Prepare the cart first.", 422
            )
        if workflow.get_proposal(identity, latest["id"])["approval_status"] != "expired":
            raise Problem("BASKET_NOT_EXPIRED", "This basket has not expired.", 409)
    when, destination = terms_for(latest, policy)
    prepared = CartPurchaseRequest(
        delivery_date=when, destination=destination, request_id=body.request_id
    )
    summary = f"Refreshed my cart's prices and stock for {when} to {destination}."
    return prepare_from_cart(identity, cid, prepared, service, summary, require_expired=not retried)


def prepare_from_cart_once(identity, cid, body, service, summary=None, require_expired=False):
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
        replay = replay_of(identity, old, messages, digest)
        if replay:
            return replay
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
        refuse_if_ordered(c, cid)
        limits = customer_constraints(c, cid)
    stored = cart_plan(messages)
    tid = uuid4()
    key = "cart-" + fingerprint({"conversation": str(cid), "key": body.request_id})
    summary = summary or "Prepared from my cart for " + f"{body.delivery_date} to {body.destination}."
    link = {
        "check_busy": True,
        "check_ordered": True,
        "require_expired": require_expired,
        "basis": basis_of(messages),
        "write": {"key": body.request_id, "digest": digest, "summary": summary, "plan": None},
    }
    pid, left_out, _ = prepare_basket(
        identity, cid, stored, body.delivery_date, body.destination, key, limits, service, tid, link
    )
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


def placed_order(c, cid):
    """The order id if the conversation's CURRENT cart was already ordered, else None.

    The current cart is the latest stored plan. It is ordered when the latest basket has an order and no
    newer plan was stored after that basket (a new plan is a new customer request, a new cart)."""
    row = c.execute(
        """SELECT m.id AS message_id, p.order_id FROM conversation_messages m
        JOIN proposals p ON p.id=m.proposal_id
        WHERE m.conversation_id=%s ORDER BY m.id DESC LIMIT 1""",
        (cid,),
    ).fetchone()
    if not row or not row["order_id"]:
        return None
    newer = c.execute(
        "SELECT 1 FROM conversation_messages WHERE conversation_id=%s AND id>%s AND meal_plan IS NOT NULL",
        (cid, row["message_id"]),
    ).fetchone()
    return None if newer else row["order_id"]


def refuse_if_ordered(c, cid):
    order_id = placed_order(c, cid)
    if order_id:
        raise Problem(
            "BASKET_ALREADY_ORDERED",
            "This order was already placed. Start a new request for another order.",
            409,
            details={"order_id": str(order_id)},
        )


def plan_signature(plan_data):
    """What a cart holds, for comparing two stored plans: (name, product, amount, unit) per item."""
    try:
        return sorted(
            (i["name"], i.get("product_id"), str(i.get("amount")), i["unit"])
            for i in plan_data["ingredients"]
        )
    except (KeyError, TypeError):
        return None


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
            brief = request_brief.load(c, cid, tid)
            recorded = c.execute("SELECT request_brief FROM conversation_turns WHERE id=%s", (tid,)).fetchone()
            latest = latest_terms(c, cid)
            ordered = placed_order(c, cid)
            current = c.execute(
                "SELECT meal_plan FROM conversation_messages WHERE conversation_id=%s AND meal_plan IS NOT NULL ORDER BY id DESC LIMIT 1",
                (cid,),
            ).fetchone()
        if brief and not brief.can_build:
            return None
        if (settings().guardrail_mode == "enforce" or brief) and not recorded["request_brief"]:
            return None, [], "Your ingredient list is saved; the request still needs checking before a basket can be prepared."
        if ordered and (
            not current or plan_signature(current["meal_plan"]) == plan_signature(stored)
        ):
            return (
                None  # the cart that was ordered: no second basket (a changed plan is a new cart)
            )
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
        link = {"check_busy": False, "check_ordered": not ordered, "basis": None, "write": None}
        pid, left_out, notice = prepare_basket(
            identity, cid, stored, when, destination, key, limits, service, tid, link
        )
    except Problem as exc:
        if exc.code not in ("EMPTY_CART", "CART_INCOMPLETE"):
            event("cart.auto_prepare_failed", error_code=exc.code, conversation_id=str(cid))
            return None, [], "Your ingredient list is saved, but I couldn’t finish checking the basket. Please try again."
        return None
    except Exception as exc:  # a display convenience: it must never fail the customer's turn
        event("cart.auto_prepare_failed", error_code=type(exc).__name__, conversation_id=str(cid))
        return None, [], "Your ingredient list is saved, but I couldn’t finish checking the basket. Please try again."
    if latest and str(latest["id"]) == str(pid):
        return None
    return pid, left_out, notice


# --- the customer's own pack-count edit on the card ----------------------------------------------------


def amount_for_packs(product, unit, packs):
    """The plan amount (in the ingredient's unit) that is exactly `packs` sales units, from catalog
    evidence only: packs x (unit per sales unit), rounded DOWN to 4 decimals (the plan's precision) and
    checked to buy exactly that many packs. 0 is a removal."""
    if packs == 0:
        return "0"
    per_sales, _, conflicting = catalog.per_sales_for(product, unit)
    if conflicting or not per_sales:
        raise Problem(
            "CART_QUANTITY_UNKNOWN",
            "There is no catalog evidence to set this quantity in packs.",
            422,
        )
    amount = Decimal(floor(Fraction(packs) * per_sales * 10000)) / Decimal(10000)
    for whole in (True, False):
        got = catalog.quantity(product, amount, unit, whole)
        if got["status"] == "derived" and Fraction(got["sales_quantity"]) == packs and amount > 0:
            return format(amount.normalize(), "f")
    raise Problem(
        "CART_QUANTITY_UNKNOWN",
        "This quantity cannot be set exactly in packs for this product.",
        422,
    )


def edit_cart(identity, cid, body, service):
    return retrying(lambda: edit_cart_once(identity, cid, body, service))


def edit_cart_once(identity, cid, body, service):
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only a buyer session can edit the cart.", 403)
    digest = fingerprint({"edit": sorted((x.product_id, x.sales_quantity) for x in body.lines)})
    with connection() as c:
        _, policy, _, _ = context(c, identity)
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
        replay = replay_of(identity, old, messages, digest)
        if replay:
            return replay
        unfinished = c.execute(
            "SELECT state FROM conversation_turns WHERE conversation_id=%s AND state!='complete'",
            (cid,),
        ).fetchone()
        if unfinished:
            raise Problem("CONVERSATION_BUSY", "A response is in progress.", 409, 3)
        refuse_if_ordered(c, cid)
        limits = customer_constraints(c, cid)
        latest = latest_terms(c, cid)
    stored = cart_plan(messages)
    if isinstance(stored, dict) and stored.get("recipe_plan_id"):
        raise Problem("RECIPE_BASKET_LOCKED", RECIPE_LOCKED_REASON, 422)
    try:
        plan = MealPlan.model_validate(stored)
    except ValidationError:
        raise Problem("CART_NOT_VERIFIED", "The cart could not be verified.", 422) from None
    by_product = {}
    for index, item in enumerate(plan.ingredients):
        if item.product_id:
            by_product.setdefault(item.product_id, []).append(index)
    for line in body.lines:
        if line.product_id not in by_product:
            raise Problem(
                "ITEM_NOT_IN_CART",
                "That product is not in the cart.",
                422,
                details={"product_id": line.product_id},
            )
    tid = uuid4()
    session = ToolSession(auth.internal_agent(identity) | {"_turn_id": str(tid)}, service)
    matched = [i for i in plan.ingredients if i.product_id]
    if not session.restore_plan(
        plan.model_copy(update={"ingredients": matched}).model_dump(mode="json")
    ):
        raise Problem("CART_NOT_VERIFIED", "The cart could not be verified.", 422)
    edited = plan.model_dump(mode="json")
    told = []
    for line in body.lines:
        first, *rest = by_product[line.product_id]
        item = edited["ingredients"][first]
        item["amount"] = amount_for_packs(
            session.products[line.product_id], item["unit"], line.sales_quantity
        )
        for other in rest:  # ingredients that share the product: the first one carries the quantity
            edited["ingredients"][other]["amount"] = "0"
        told.append(
            f"{item['name']} removed"
            if line.sales_quantity == 0
            else f"{item['name']}: {line.sales_quantity} packs"
        )
    key = "edit-" + fingerprint({"conversation": str(cid), "key": body.request_id})
    if edited == stored and latest:
        return answer(identity, latest["id"], split_plain(plan)[1])  # nothing changed: no revision
    when, destination = terms_for(latest, policy)
    summary = "I changed the cart on the card: " + ", ".join(told) + "."
    link = {
        "check_busy": True,
        "check_ordered": True,
        "basis": basis_of(messages),
        "write": {"key": body.request_id, "digest": digest, "summary": summary, "plan": edited},
    }
    pid, left_out, _ = prepare_basket(
        identity, cid, edited, when, destination, key, limits, service, tid, link
    )
    return answer(identity, pid, left_out)
