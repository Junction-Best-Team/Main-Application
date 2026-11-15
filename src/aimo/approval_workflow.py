"""Short transactions serialize each buyer, then lock identities and proposal state.
Privileged policy/authority changes must acquire the same buyer lock first.
No network call or human wait occurs while these locks are held.
"""

from decimal import Decimal
from uuid import uuid4

from psycopg import sql

from aimo import cancellations
from aimo import clock as demo_clock
from aimo import meal_authorization as meals
from aimo.approval_policy import can_approve, evaluate_purchase
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, js, now
from aimo.purchases import build_snapshot, context, material_fingerprint
from aimo.schemas import (
    CommitRequest,
    Constraint,
    DecisionRequest,
    PrepareRequest,
    PurchaseRequest,
)


def stored_constraints(request):
    """The server-written POL-008 record inside a stored request; absent for most requests."""
    return request.get("constraints")


def public_request(request):
    """What callers see: the stored request without the server-only constraint record."""
    return {k: v for k, v in request.items() if k != "constraints"}


def audit(c, pid, actor, event, detail):
    c.execute(
        "INSERT INTO audit_events(proposal_id,actor_id,event,detail) VALUES(%s,%s,%s,%s)",
        (pid, actor, event, js(detail)),
    )


def proposal(c, pid, identity, lock=False):
    p = c.execute(
        "SELECT * FROM proposals WHERE id=%s AND buyer_id=%s" + (" FOR UPDATE" if lock else ""),
        (pid, identity["buyer_id"]),
    ).fetchone()
    if not p or (identity["role"] == "agent" and p["agent_id"] != identity["id"]):
        raise Problem("NOT_FOUND", "Purchase not found.", 404)
    if identity["role"] == "scheduler":
        from aimo import scheduler

        # The scheduler sees only the proposals that belong to one of its runs (CNF-023).
        if not scheduler.owns_proposal(c, pid, identity["buyer_id"]):
            raise Problem("NOT_FOUND", "Purchase not found.", 404)
    r = c.execute(
        "SELECT * FROM proposal_revisions WHERE proposal_id=%s AND revision=%s",
        (pid, p["current_revision"]),
    ).fetchone()
    a = c.execute(
        "SELECT * FROM approvals WHERE proposal_id=%s AND revision=%s", (pid, p["current_revision"])
    ).fetchone()
    return p, r, a


def append_revision(
    c, pid, revision, identity, request, snapshot, expires, policy, actor, approvers, evaluated=None
):
    evaluated = evaluated or evaluate_purchase(
        request,
        snapshot,
        policy["rules"],
        [a["authority"] for a in approvers],
        stored_constraints(request),
    )
    fp = material_fingerprint(request, snapshot, policy["version"])
    c.execute(
        """INSERT INTO proposal_revisions VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            pid,
            revision,
            policy["version"],
            js(request),
            js(snapshot),
            fp,
            evaluated["policy_outcome"],
            js(evaluated["reasons"]),
            js(evaluated["required_exceptions"]),
            expires,
        ),
    )
    c.execute(
        "UPDATE approvals SET status='superseded' WHERE proposal_id=%s AND status IN ('pending','approved')",
        (pid,),
    )
    if evaluated["policy_outcome"] == "approval_required":
        c.execute(
            "INSERT INTO approvals(id,proposal_id,revision,status,fingerprint) VALUES(%s,%s,%s,'pending',%s)",
            (uuid4(), pid, revision, fp),
        )
    c.execute(
        "UPDATE proposals SET current_revision=%s,updated_at=now() WHERE id=%s", (revision, pid)
    )
    audit(
        c,
        pid,
        identity["id"],
        "proposal_prepared" if revision == 1 else "proposal_revised",
        {"revision": revision, "policy_version": policy["version"], **evaluated},
    )


def evaluation_changed(revision, evaluated):
    return any(revision[key] != evaluated[key] for key in evaluated)


def render(
    c, p, r, a, identity, *, auth_context=None, purchasing_agent=None, history=None, cancelled=None
):
    current = now()
    status = a["status"] if a else "not_required"
    recipe_basis = "saved_recipe" if r["request"].get("recipe_plan_id") else "free_form"
    buyer, policy, actor, approvers = auth_context or context(c, identity)
    historical = r["revision"] != p["current_revision"]
    order = (
        c.execute("SELECT id,revision FROM orders WHERE id=%s", (p["order_id"],)).fetchone()
        if p["order_id"]
        else None
    )
    committed = order is not None and order["revision"] == r["revision"]
    fulfilment = None
    if order:  # simulated and derived on read; the order itself is never updated
        placed = c.execute(
            """SELECT o.created_at, q.request->>'delivery_date' AS delivery_date
            FROM orders o JOIN proposal_revisions q ON q.proposal_id=o.proposal_id AND q.revision=o.revision
            WHERE o.id=%s""",
            (order["id"],),
        ).fetchone()
        fulfilment = demo_clock.fulfilment_view(c, p["buyer_id"])(
            placed["delivery_date"], placed["created_at"]
        )
    if historical:
        status = "superseded"
    elif not committed and (
        cancelled if cancelled is not None else cancellations.is_cancelled(c, p["id"])
    ):
        status = "cancelled"  # CNF-035: an append-only record next to the request
    elif not committed and status != "rejected":
        if (a is None or a["status"] == "superseded") and meals.is_withdrawn(c, p["id"]):
            status = "authorization_withdrawn"  # POL-010; withdrawal supersedes open approvals
        elif r["expires_at"] <= current:
            status = "expired"
        elif policy["version"] != r["policy_version"]:
            status = "policy_changed"
        else:
            # The agent holds no authority (Q-35); only its being revoked invalidates a basket.
            if purchasing_agent is None:
                purchasing_agent = c.execute(
                    "SELECT active FROM identities WHERE id=%s AND buyer_id=%s",
                    (p["agent_id"], p["buyer_id"]),
                ).fetchone()
            if not (purchasing_agent and purchasing_agent["active"]):
                status = "authority_changed"
            else:
                evaluated = evaluate_purchase(
                    r["request"],
                    r["snapshot"],
                    policy["rules"],
                    [x["authority"] for x in approvers],
                    stored_constraints(r["request"]),
                )
                if evaluation_changed(r, evaluated):
                    status = "authority_changed"
    if status == "approved" and not p["order_id"]:
        decision_actor = next((x for x in approvers if x["id"] == a["actor_id"]), None)
        if not decision_actor or not can_approve(
            decision_actor["authority"],
            Decimal(r["snapshot"]["gross_total"]),
            r["snapshot"]["currency"],
            r["required_exceptions"],
        ):
            status = "authority_changed"
    eligible = r["policy_outcome"] == "ready_to_commit" or (
        r["policy_outcome"] == "approval_required" and status == "approved"
    )
    if historical:
        action = {"type": "view_current_proposal", "tool": "get_proposal"}
    elif committed:
        action = {"type": "complete", "tool": "get_order"}
    elif status in ("rejected", "cancelled"):
        action = {"type": "stop"}
    elif status in (
        "expired",
        "superseded",
        "policy_changed",
        "authority_changed",
        "authorization_withdrawn",
    ):
        action = {"type": "request_fresh_proposal", "tool": "prepare_order"}
    elif r["policy_outcome"] == "denied":
        action = (
            {"type": "revise_request", "tool": "prepare_order"}
            if recipe_basis == "saved_recipe"
            else {"type": "stop"}
        )
    elif r["policy_outcome"] == "needs_resolution":
        action = {"type": "revise_request", "tool": "prepare_order"}
    elif eligible:
        action = {"type": "commit", "tool": "commit_order"}
    else:
        action = {"type": "wait", "tool": "get_proposal", "poll_after_seconds": 30}
    can_decide = bool(
        actor["role"] == "approver"
        and status == "pending"
        and not p["order_id"]
        and can_approve(
            actor["authority"],
            Decimal(r["snapshot"]["gross_total"]),
            r["snapshot"]["currency"],
            r["required_exceptions"],
        )
    )
    return {
        "proposal_id": str(p["id"]),
        "revision": r["revision"],
        "fingerprint": r["fingerprint"],
        "current_revision": p["current_revision"],
        "committed_revision": order["revision"] if order else None,
        "current_proposal_url": f"{settings().public_base_url}/purchases/{p['id']}",
        "policy_version": r["policy_version"],
        "policy_outcome": r["policy_outcome"],
        "recipe_basis": recipe_basis,
        "approval_status": status,
        "order_status": "accepted_mock" if committed else "not_placed",
        "fulfilment": fulfilment,
        "reasons": r["reasons"],
        "expires_at": r["expires_at"],
        "next_action": action,
        "approval_id": str(a["id"]) if a else None,
        "approval_url": f"{settings().public_base_url}/approvals/{a['id']}" if a else None,
        "order_id": str(order["id"]) if committed else None,
        "buyer_id": buyer["id"],
        "agent_id": p["agent_id"],
        "request": public_request(r["request"]),
        "snapshot": r["snapshot"],
        "can_decide": can_decide,
        "history": history
        if history is not None
        else [
            dict(row)
            for row in c.execute(
                "SELECT event,actor_id,detail,created_at FROM audit_events WHERE proposal_id=%s ORDER BY id",
                (p["id"],),
            ).fetchall()
        ],
    }


def get_proposal(identity, pid, revision=None):
    """A proposal by ID: the current revision, or an earlier one by number (PER-003).

    Scoped like every read (another buyer or an agent that did not prepare it gets 404). An
    earlier revision renders as superseded with its own totals, approval row (if any) and a
    pointer to the current revision; an unknown revision is 404.
    """
    with connection() as c:
        p, r, a = proposal(c, pid, identity)
        if revision is not None and revision != p["current_revision"]:
            r = c.execute(
                "SELECT * FROM proposal_revisions WHERE proposal_id=%s AND revision=%s",
                (p["id"], revision),
            ).fetchone()
            if not r:
                raise Problem("NOT_FOUND", "Revision not found.", 404)
            a = c.execute(
                "SELECT * FROM approvals WHERE proposal_id=%s AND revision=%s",
                (p["id"], revision),
            ).fetchone()
        return render(c, p, r, a, identity)


def prior_preparation(c, identity, key, payload_hash):
    old = c.execute(
        "SELECT proposal_id,payload_hash FROM prepare_requests WHERE buyer_id=%s AND agent_id=%s AND key=%s",
        (identity["buyer_id"], identity["id"], key),
    ).fetchone()
    if old:
        if old["payload_hash"] != payload_hash:
            raise Problem(
                "IDEMPOTENCY_CONFLICT",
                "This preparation key already identifies a different purchase request.",
            )
        return render(c, *proposal(c, old["proposal_id"], identity), identity)
    return None


def prepare_order(identity, request: PrepareRequest, connector, constraints=None):
    """`constraints` is the server-only POL-008 record (never a model or API field). It is stored
    in the revision's request JSON under `constraints`, so the fingerprint and the retry hash
    cover it; the key is omitted when there is none, leaving older requests unchanged."""
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    if constraints:
        payload["constraints"] = [
            Constraint.model_validate(entry).model_dump(mode="json") for entry in constraints
        ]
    payload_hash = fingerprint(payload)
    with connection() as c:
        context(c, identity)
        old = prior_preparation(c, identity, request.idempotency_key, payload_hash)
        if old:
            return old
        if request.recipe_plan_id:
            from aimo.recipes import validate_basket

            recipe_proposal = validate_basket(c, identity, request)
    snapshot, expires, version = build_snapshot(identity, request, connector)
    with connection() as c:
        _, policy, actor, approvers = context(c, identity, lock=True)
        old = prior_preparation(c, identity, request.idempotency_key, payload_hash)
        if old:
            return old
        if request.recipe_plan_id:
            # Recheck after supplier I/O. Serialize only this short persistence
            # transaction; proposal creation and the plan lock commit together.
            if validate_basket(c, identity, request) != recipe_proposal:
                raise Problem(
                    "RECIPE_PROPOSAL_CHANGED", "Another request refreshed this basket; reload it."
                )
        if version != policy["version"]:
            raise Problem("POLICY_CHANGED", "Policy changed during lookup; prepare again.")
        previous = recipe_proposal if request.recipe_plan_id else None
        pid = previous["id"] if previous else uuid4()
        revision = previous["revision"] + 1 if previous else 1
        if not previous:
            c.execute(
                "INSERT INTO proposals(id,buyer_id,agent_id,current_revision) VALUES(%s,%s,%s,1)",
                (pid, identity["buyer_id"], identity["id"]),
            )
        append_revision(
            c,
            pid,
            revision,
            identity,
            payload,
            snapshot,
            expires,
            policy,
            actor,
            approvers,
        )
        c.execute(
            "INSERT INTO prepare_requests(buyer_id,agent_id,key,payload_hash,proposal_id) VALUES(%s,%s,%s,%s,%s)",
            (identity["buyer_id"], identity["id"], request.idempotency_key, payload_hash, pid),
        )
        if request.recipe_plan_id:
            c.execute(
                "UPDATE recipe_plans SET locked=true,proposal_id=%s WHERE id=%s",
                (pid, request.recipe_plan_id),
            )
        return render(c, *proposal(c, pid, identity), identity)


def approval_detail(identity, aid):
    with connection() as c:
        a = c.execute(
            """SELECT a.* FROM approvals a JOIN proposals p ON p.id=a.proposal_id WHERE a.id=%s AND p.buyer_id=%s""",
            (aid, identity["buyer_id"]),
        ).fetchone()
        if not a:
            raise Problem("NOT_FOUND", "Approval not found.", 404)
        p, r, current_a = proposal(c, a["proposal_id"], identity)
        if a["revision"] != p["current_revision"]:
            r = c.execute(
                "SELECT * FROM proposal_revisions WHERE proposal_id=%s AND revision=%s",
                (p["id"], a["revision"]),
            ).fetchone()
            return render(c, p, r, a, identity)
        return render(c, p, r, current_a, identity)


def list_approvals(identity, offset=0, limit=20):
    with connection() as c:
        # One consistent read snapshot; permissions are always rechecked on a decision.
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        auth_context = context(c, identity)
        rows = c.execute(
            """SELECT p.*,r.revision,r.policy_version,r.request,r.snapshot,r.fingerprint,
          r.policy_outcome,r.reasons,r.required_exceptions,r.expires_at,
          a.id AS approval_id,a.status AS approval_status,a.actor_id AS approval_actor,
          a.fingerprint AS approval_fingerprint,i.active AS agent_active
          FROM proposals p JOIN approvals a ON a.proposal_id=p.id AND a.revision=p.current_revision
          JOIN proposal_revisions r ON r.proposal_id=p.id AND r.revision=p.current_revision
          JOIN buyers b ON b.id=p.buyer_id
          JOIN identities i ON i.id=p.agent_id AND i.buyer_id=p.buyer_id
          WHERE p.buyer_id=%s AND a.status='pending' AND p.order_id IS NULL AND r.expires_at>%s AND r.policy_version=b.current_policy
          AND NOT EXISTS (SELECT 1 FROM order_request_cancellations x WHERE x.proposal_id=p.id)
          ORDER BY r.expires_at,p.id LIMIT %s OFFSET %s""",
            (identity["buyer_id"], now(), limit + 1, offset),
        ).fetchall()
        page = rows[:limit]
        histories = {row["id"]: [] for row in page}
        if page:
            for event in c.execute(
                "SELECT proposal_id,event,actor_id,detail,created_at FROM audit_events WHERE proposal_id=ANY(%s) ORDER BY id",
                (list(histories),),
            ).fetchall():
                pid = event.pop("proposal_id")
                histories[pid].append(event)
        return {
            "items": [
                render(
                    c,
                    row,
                    row,
                    {
                        "id": row["approval_id"],
                        "status": row["approval_status"],
                        "actor_id": row["approval_actor"],
                        "fingerprint": row["approval_fingerprint"],
                    },
                    identity,
                    auth_context=auth_context,
                    purchasing_agent={
                        "active": row["agent_active"],
                    },
                    history=histories[row["id"]],
                    cancelled=False,  # cancelled requests are filtered out of the inbox above
                )
                for row in page
            ],
            "next_offset": offset + limit if len(rows) > limit else None,
        }


def record_human_decision(identity, aid, decision: DecisionRequest):
    if identity["role"] != "approver":
        raise Problem("FORBIDDEN", "Only a buyer session can decide.", 403)
    with connection() as c:
        _, policy, actor, _ = context(c, identity, lock=True)
        a = c.execute(
            "SELECT a.* FROM approvals a JOIN proposals p ON p.id=a.proposal_id WHERE a.id=%s AND p.buyer_id=%s",
            (aid, identity["buyer_id"]),
        ).fetchone()
        if not a:
            raise Problem("NOT_FOUND", "Approval not found.", 404)
        p, r, current_a = proposal(c, a["proposal_id"], identity, lock=True)
        if decision.revision != r["revision"] or a["revision"] != r["revision"]:
            raise Problem("STALE_REVISION", "Review the current proposal revision.")
        if p["order_id"] or r["expires_at"] <= now() or policy["version"] != r["policy_version"]:
            raise Problem(
                "DECISION_CLOSED", "This proposal is finalized, expired or under an older policy."
            )
        if not can_approve(
            actor["authority"],
            Decimal(r["snapshot"]["gross_total"]),
            r["snapshot"]["currency"],
            r["required_exceptions"],
        ):
            raise Problem(
                "APPROVAL_SCOPE", "This exception or amount exceeds your approval authority.", 403
            )
        wanted = "approved" if decision.decision == "approve" else "rejected"
        if a["status"] == wanted and a["actor_id"] == identity["id"]:
            return render(c, p, r, a, identity)
        if a["status"] != "pending":
            raise Problem("DECISION_CONFLICT", "A decision has already been recorded.")
        c.execute(
            "UPDATE approvals SET status=%s,actor_id=%s,decided_at=%s WHERE id=%s",
            (wanted, identity["id"], now(), aid),
        )
        audit(
            c,
            p["id"],
            identity["id"],
            wanted,
            {
                "revision": r["revision"],
                "policy_version": policy["version"],
                "fingerprint": r["fingerprint"],
            },
        )
        return render(c, *proposal(c, p["id"], identity), identity)


def prior_result(c, identity, request, *, any_key=False):
    """Saved receipt for a repeated request. With `any_key` (customer confirmation, CNF-011) an
    order already placed on this exact revision answers whatever the key; commit keeps its own
    ALREADY_COMMITTED for a new key."""
    row = c.execute(
        "SELECT * FROM idempotency WHERE buyer_id=%s AND key=%s",
        (identity["buyer_id"], request.idempotency_key),
    ).fetchone()
    if row:
        if row["payload_hash"] != fingerprint(
            {"proposal_id": str(request.proposal_id), "revision": request.revision}
        ):
            raise Problem(
                "IDEMPOTENCY_CONFLICT", "This key already identifies another commit payload."
            )
        proposal(c, request.proposal_id, identity)
        return c.execute("SELECT receipt FROM orders WHERE id=%s", (row["order_id"],)).fetchone()[
            "receipt"
        ]
    if any_key:
        proposal(c, request.proposal_id, identity)
        order = c.execute(
            "SELECT revision,receipt FROM orders WHERE proposal_id=%s AND buyer_id=%s",
            (request.proposal_id, identity["buyer_id"]),
        ).fetchone()
        if order and order["revision"] == request.revision:
            used = c.execute(
                "SELECT proposal_id,revision FROM customer_confirmations WHERE buyer_id=%s AND key=%s",
                (identity["buyer_id"], request.idempotency_key),
            ).fetchone()
            if used and (
                str(used["proposal_id"]) != str(request.proposal_id)
                or used["revision"] != request.revision
            ):
                raise Problem(
                    "IDEMPOTENCY_CONFLICT", "This confirmation key identifies different terms."
                )
            return order["receipt"]
    return None


def authorize_commit(r, a, approvers, snapshot, evaluation):
    if r["expires_at"] <= now():
        raise Problem("PROPOSAL_EXPIRED", "Prepare a fresh proposal.")
    if a and a["status"] == "rejected":
        raise Problem("APPROVAL_REJECTED", "Buyer rejected this purchase.")
    if evaluation["policy_outcome"] == "ready_to_commit":
        return
    if evaluation["policy_outcome"] != "approval_required":
        raise Problem("COMMIT_BLOCKED", "Current policy or commercial evidence blocks commitment.")
    approver = next((x for x in approvers if a and x["id"] == a["actor_id"]), None)
    if (
        not a
        or a["status"] != "approved"
        or a["fingerprint"] != r["fingerprint"]
        or not approver
        or not can_approve(
            approver["authority"],
            Decimal(snapshot["gross_total"]),
            snapshot["currency"],
            evaluation["required_exceptions"],
        )
    ):
        raise Problem(
            "APPROVAL_REQUIRED",
            "An exact-revision decision by a currently authorized buyer is required.",
        )


def require_commit_authority(c, identity, p, r, snapshot, evaluated, approvers):
    """Who may commit, by role. Every role has its own branch and an unknown one is refused.

    agent:     no agent can authorize a purchase; it needs a customer confirmation recorded
               against this exact revision and fingerprint. Blocked outcomes skip the check and
               are refused as COMMIT_BLOCKED by authorize_commit.
    scheduler: only against a valid scheduled authorization (aimo.scheduler).
    approver:  the human customer; the confirmation is that approver's own action.
    """
    role = identity["role"]
    if role == "agent":
        if evaluated["policy_outcome"] not in ("ready_to_commit", "approval_required"):
            return
        confirmations = c.execute(
            """SELECT actor_id FROM customer_confirmations
            WHERE proposal_id=%s AND revision=%s AND fingerprint=%s""",
            (p["id"], r["revision"], r["fingerprint"]),
        ).fetchall()
        confirmed_ids = {item["actor_id"] for item in confirmations}
        if not any(
            candidate["id"] in confirmed_ids
            and can_approve(
                candidate["authority"],
                Decimal(snapshot["gross_total"]),
                snapshot["currency"],
                evaluated["required_exceptions"],
            )
            for candidate in approvers
        ):
            raise Problem(
                "CUSTOMER_CONFIRMATION_REQUIRED",
                "Confirm these exact terms in the product.",
                403,
            )
    elif role == "scheduler":
        from aimo import scheduler

        scheduler.ensure_commit_allowed(c, identity, p, r, snapshot, evaluated)
    elif role != "approver":
        raise Problem("FORBIDDEN", "This identity role cannot commit a purchase.", 403)


def commit_order(identity, request: CommitRequest, connector):
    with connection() as c:
        context(c, identity)
        old = prior_result(c, identity, request)
        if old:
            return old
        p, r, _ = proposal(c, request.proposal_id, identity)
        if r["revision"] != request.revision:
            raise Problem("STALE_REVISION", "Use the current revision.")
        if p["order_id"]:
            raise Problem("ALREADY_COMMITTED", "Use the original idempotency key or get_order.")
        if r["expires_at"] <= now():
            raise Problem("PROPOSAL_EXPIRED", "Prepare a fresh proposal.")
        purchase = PurchaseRequest.model_validate(public_request(r["request"]))
    snapshot, expires, version = build_snapshot(identity, purchase, connector)
    with connection() as c:
        _, policy, actor, approvers = context(c, identity, lock=True)
        old = prior_result(c, identity, request)
        if old:
            return old
        p, r, a = proposal(c, request.proposal_id, identity, lock=True)
        if r["revision"] != request.revision:
            raise Problem("STALE_REVISION", "Another caller revised this proposal.")
        if p["order_id"]:
            raise Problem("ALREADY_COMMITTED", "One order already exists for this proposal.")
        meals.ensure_active(c, p["id"])  # POL-010: a withdrawn authorization never commits
        cancellations.ensure_not_cancelled(c, p["id"])  # CNF-035: a cancelled request never commits
        if version != policy["version"]:
            raise Problem(
                "POLICY_CHANGED", "Policy changed during lookup; retry with fresh evidence."
            )
        if a and a["status"] == "rejected":
            raise Problem("APPROVAL_REJECTED", "Buyer rejected this purchase.")
        if r["expires_at"] <= now():
            raise Problem("PROPOSAL_EXPIRED", "Prepare a fresh proposal.")
        fresh_fp = material_fingerprint(r["request"], snapshot, policy["version"])
        evaluated = evaluate_purchase(
            r["request"],
            snapshot,
            policy["rules"],
            [x["authority"] for x in approvers],
            stored_constraints(r["request"]),
        )
        # Commercial terms can be identical while effective purchasing authority changes.
        # Persist the new decision and any approval in this same locked transaction.
        if fresh_fp != r["fingerprint"] or evaluation_changed(r, evaluated):
            append_revision(
                c,
                p["id"],
                r["revision"] + 1,
                identity,
                r["request"],
                snapshot,
                expires,
                policy,
                actor,
                approvers,
                evaluated=evaluated,
            )
            return {
                "status": "revised",
                **render(c, *proposal(c, p["id"], identity), identity),
            }
        require_commit_authority(c, identity, p, r, snapshot, evaluated, approvers)
        authorize_commit(r, a, approvers, snapshot, evaluated)
        oid = uuid4()
        receipt = {
            "order_id": str(oid),
            "proposal_id": str(p["id"]),
            "revision": r["revision"],
            "policy_version": policy["version"],
            "status": "accepted_mock",
            "policy_outcome": r["policy_outcome"],
            "approval_status": a["status"] if a else "not_required",
            "order_status": "accepted_mock",
            "reasons": r["reasons"],
            "expires_at": r["expires_at"].isoformat(),
            "next_action": {"type": "complete", "tool": "get_order"},
            "label": "Accepted by demo order service",
            "upstream_order_placed": False,
            "inventory_reserved": False,
            "buyer_id": identity["buyer_id"],
            "gross_total": snapshot["gross_total"],
            "currency": snapshot["currency"],
            "evidence_mode": snapshot["mode"],
            "accepted_at": now().isoformat(),
            "explanation": "Current policy, commercial evidence and any required exact-revision buyer approval were checked.",
        }
        if identity["role"] == "scheduler":
            from aimo import scheduler

            receipt["scheduled_run"] = scheduler.receipt_note(c, p["id"])  # CNF-036 order note
        c.execute(
            "INSERT INTO orders(id,proposal_id,buyer_id,revision,receipt) VALUES(%s,%s,%s,%s,%s)",
            (oid, p["id"], identity["buyer_id"], r["revision"], js(receipt)),
        )
        c.execute("UPDATE proposals SET order_id=%s WHERE id=%s", (oid, p["id"]))
        c.execute(
            "INSERT INTO idempotency VALUES(%s,%s,%s,%s)",
            (
                identity["buyer_id"],
                request.idempotency_key,
                fingerprint({"proposal_id": str(p["id"]), "revision": r["revision"]}),
                oid,
            ),
        )
        audit(
            c,
            p["id"],
            identity["id"],
            "accepted_mock",
            {"receipt": receipt, "revalidated_at": snapshot["observed_at"]},
        )
        return receipt


def get_receipt(identity, proposal_id):
    """The stored receipt of a proposal the identity may see (the buyer's own), via get_order, plus
    the delivery date, destination and simulated fulfilment, derived on read (JNP3-FUL)."""
    with connection() as c:
        context(c, identity)
        p, _, _ = proposal(c, proposal_id, identity)
        if not p["order_id"]:
            raise Problem(
                "NO_RECEIPT", "This purchase has no order yet, so there is no receipt.", 404
            )
        row = c.execute(
            """SELECT o.receipt, o.created_at, q.request->>'delivery_date' AS delivery_date,
            q.request->>'destination' AS destination
            FROM orders o JOIN proposal_revisions q ON q.proposal_id=o.proposal_id AND q.revision=o.revision
            WHERE o.id=%s AND o.buyer_id=%s""",
            (p["order_id"], identity["buyer_id"]),
        ).fetchone()
        if not row:
            raise Problem("NOT_FOUND", "Order not found.", 404)
        return {
            **row["receipt"],
            "delivery_date": demo_clock.stored_date(row["delivery_date"]),
            "destination": row["destination"],
            "fulfilment": demo_clock.fulfilment_view(c, identity["buyer_id"])(
                row["delivery_date"], row["created_at"]
            ),
        }


def get_order(identity, oid):
    with connection() as c:
        context(c, identity)
        order = c.execute(
            "SELECT * FROM orders WHERE id=%s AND buyer_id=%s", (oid, identity["buyer_id"])
        ).fetchone()
        if not order:
            raise Problem("NOT_FOUND", "Order not found.", 404)
        proposal(c, order["proposal_id"], identity)
        return order["receipt"]


# --- CNF-021: remove proposals and approvals that never became orders ---------------------------

# Records that must stay forever (owner principle: keep history). A proposal that any of these
# tables references is not "unfinished" and is never purged, wherever the column is called.
# They are scheduler tables created by a later migration, so they may not exist yet.
PROTECTED_TABLES = ("scheduled_runs", "order_request_cancellations")


def _protected(c):
    """SQL that excludes proposals referenced by a protected table (found via its foreign key)."""
    rows = c.execute(
        """SELECT cl.relname AS tbl, a.attname AS col FROM pg_constraint k
        JOIN pg_class cl ON cl.oid=k.conrelid
        CROSS JOIN LATERAL unnest(k.conkey, k.confkey) AS u(refering, referenced)
        JOIN pg_attribute fa ON fa.attrelid=k.confrelid AND fa.attnum=u.referenced AND fa.attname='id'
        JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=u.refering
        WHERE k.contype='f' AND k.confrelid='proposals'::regclass AND cl.relname = ANY(%s)
        AND cl.relnamespace=current_schema()::regnamespace ORDER BY 1,2""",
        (list(PROTECTED_TABLES),),
    ).fetchall()
    return "".join(
        " AND NOT EXISTS (SELECT 1 FROM {} x WHERE x.{} = p.id)".format(
            sql.Identifier(r["tbl"]).as_string(c), sql.Identifier(r["col"]).as_string(c)
        )
        for r in rows
    )


# A proposal is unfinished when it has no order, no protected record points at it, and the
# expiry of its current revision is older than the cutoff. Rows are locked with SKIP LOCKED, under
# the buyer lock, like every purchasing transaction, so a commit racing the cleanup is serialized
# by the same lock.
def _unfinished(c):
    return """FROM proposals p
 JOIN proposal_revisions r ON r.proposal_id=p.id AND r.revision=p.current_revision
 WHERE p.buyer_id=%s AND p.order_id IS NULL
 AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.proposal_id=p.id)
 AND r.expires_at < %s""" + _protected(c)


def purge_batch(c, proposal_ids, older_than):
    """Remove these proposals if they still have no order; the caller holds the buyer lock.

    Writes one purged_proposals record per proposal, deletes children first, unlinks the recipe
    plan (it becomes reusable) and the chat messages (their text stays), then the revisions and
    the proposal. The history triggers allow these DELETEs only under the local flag and only
    for a proposal with no order. Returns counts per table.
    """
    c.execute("SET LOCAL aimo.purge_unfinished = 'on'")
    ids = [
        r["id"]
        for r in c.execute(
            """SELECT p.id FROM proposals p WHERE p.id = ANY(%s::uuid[]) AND p.order_id IS NULL
            AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.proposal_id=p.id)"""
            + _protected(c)
            + " ORDER BY p.id FOR UPDATE",
            ([str(i) for i in proposal_ids],),
        ).fetchall()
    ]
    counts = dict.fromkeys(
        (
            "proposals",
            "proposal_revisions",
            "approvals",
            "audit_events",
            "customer_confirmations",
            "meal_authorization_withdrawals",
            "prepare_requests",
            "recipe_plans_unlinked",
            "conversation_messages_unlinked",
        ),
        0,
    )
    if not ids:
        return counts
    days = round(older_than.total_seconds() / 86400)
    c.execute(
        """INSERT INTO purged_proposals(proposal_id,buyer_id,created_at,last_revision,
        last_outcome,last_expires_at,period_days)
        SELECT p.id,p.buyer_id,p.created_at,p.current_revision,r.policy_outcome,r.expires_at,%s
        FROM proposals p JOIN proposal_revisions r
        ON r.proposal_id=p.id AND r.revision=p.current_revision WHERE p.id = ANY(%s)""",
        (days, ids),
    )
    for table, key in (
        ("meal_authorization_withdrawals", "meal_authorization_withdrawals"),
        ("customer_confirmations", "customer_confirmations"),
        ("approvals", "approvals"),
        ("audit_events", "audit_events"),
        ("prepare_requests", "prepare_requests"),
    ):
        counts[key] = c.execute(f"DELETE FROM {table} WHERE proposal_id = ANY(%s)", (ids,)).rowcount
    counts["recipe_plans_unlinked"] = c.execute(
        "UPDATE recipe_plans SET proposal_id=NULL, locked=false WHERE proposal_id = ANY(%s)", (ids,)
    ).rowcount
    counts["conversation_messages_unlinked"] = c.execute(
        "UPDATE conversation_messages SET proposal_id=NULL WHERE proposal_id = ANY(%s)", (ids,)
    ).rowcount
    counts["proposal_revisions"] = c.execute(
        "DELETE FROM proposal_revisions WHERE proposal_id = ANY(%s)", (ids,)
    ).rowcount
    counts["proposals"] = c.execute("DELETE FROM proposals WHERE id = ANY(%s)", (ids,)).rowcount
    return counts


def purge_unfinished_proposals(older_than, *, as_of=None, dry_run=False, batch_size=100, conn=None):
    """Remove unfinished proposals whose current revision expired more than `older_than` ago.

    `as_of` defaults to now. Short transactions of `batch_size` proposals per buyer (no network
    call, no human wait); `dry_run` only counts. With `conn` everything runs on that connection
    and the caller commits (used to run it as the restricted runtime role). Orders and anything
    on an ordered proposal are never selected. Returns the summed counts.
    """
    cutoff = (as_of or now()) - older_than
    totals = {"dry_run": dry_run, "cutoff": cutoff.isoformat()}

    def add(counts):
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value

    def run(c):
        buyers = [
            r["buyer_id"]
            for r in c.execute(
                f"SELECT DISTINCT p.buyer_id {_unfinished(c).replace('p.buyer_id=%s', 'TRUE')} "
                "ORDER BY 1",
                (cutoff,),
            ).fetchall()
        ]
        return buyers

    def one_batch(c, buyer_id):
        c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (buyer_id,))
        ids = [
            r["id"]
            for r in c.execute(
                f"SELECT p.id {_unfinished(c)} ORDER BY p.id LIMIT %s FOR UPDATE OF p SKIP LOCKED",
                (buyer_id, cutoff, batch_size),
            ).fetchall()
        ]
        if not ids:
            return 0
        if dry_run:
            return None
        counts = purge_batch(c, ids, older_than)
        add(counts)
        return counts["proposals"]

    if dry_run:
        with _use(conn) as c:
            total = c.execute(
                f"SELECT count(*) AS n {_unfinished(c).replace('p.buyer_id=%s', 'TRUE')}", (cutoff,)
            ).fetchone()["n"]
            revisions = c.execute(
                f"SELECT count(*) AS n FROM proposal_revisions WHERE proposal_id IN "
                f"(SELECT p.id {_unfinished(c).replace('p.buyer_id=%s', 'TRUE')})",
                (cutoff,),
            ).fetchone()["n"]
        totals.update(proposals=total, proposal_revisions=revisions)
        return totals
    totals.update(proposals=0)
    with _use(conn) as c:
        buyers = run(c)
    for buyer_id in buyers:
        while True:
            with _use(conn) as c:
                removed = one_batch(c, buyer_id)
            if not removed:
                break
    return totals


class _use:
    """Use the given connection as is (caller commits), or a pooled one in its own transaction."""

    def __init__(self, conn):
        self.conn, self.cm = conn, None

    def __enter__(self):
        if self.conn is not None:
            return self.conn
        self.cm = connection()
        return self.cm.__enter__()

    def __exit__(self, *exc):
        if self.cm is not None:
            return self.cm.__exit__(*exc)
