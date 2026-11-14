"""Short transactions serialize each buyer, then lock identities and proposal state.
Privileged policy/authority changes must acquire the same buyer lock first.
No network call or human wait occurs while these locks are held.
"""

from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from aimo.approval_policy import can_approve, evaluate_purchase
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, js, now
from aimo.purchases import build_snapshot, context, material_fingerprint
from aimo.schemas import (
    AgentAuthority,
    CommitRequest,
    DecisionRequest,
    PrepareRequest,
    PurchaseRequest,
)


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
        request, snapshot, policy["rules"], actor["authority"], [a["authority"] for a in approvers]
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
    c.execute("UPDATE proposals SET current_revision=%s WHERE id=%s", (revision, pid))
    audit(
        c,
        pid,
        identity["id"],
        "proposal_prepared" if revision == 1 else "proposal_revised",
        {"revision": revision, "policy_version": policy["version"], **evaluated},
    )


def evaluation_changed(revision, evaluated):
    return any(revision[key] != evaluated[key] for key in evaluated)


def render(c, p, r, a, identity, *, auth_context=None, purchasing_agent=None, history=None):
    current = now()
    status = a["status"] if a else "not_required"
    buyer, policy, actor, approvers = auth_context or context(c, identity)
    historical = r["revision"] != p["current_revision"]
    order = (
        c.execute("SELECT id,revision FROM orders WHERE id=%s", (p["order_id"],)).fetchone()
        if p["order_id"]
        else None
    )
    committed = order is not None and order["revision"] == r["revision"]
    if historical:
        status = "superseded"
    elif not committed:
        if r["expires_at"] <= current:
            status = "expired"
        elif policy["version"] != r["policy_version"]:
            status = "policy_changed"
        elif status != "rejected":
            # Buyer views must evaluate the purchasing agent, not the approver's authority.
            if purchasing_agent is None:
                purchasing_agent = c.execute(
                    "SELECT authority,active FROM identities WHERE id=%s AND buyer_id=%s",
                    (p["agent_id"], p["buyer_id"]),
                ).fetchone()
            try:
                authority = AgentAuthority.model_validate(
                    purchasing_agent["authority"]
                    if purchasing_agent and purchasing_agent["active"]
                    else {}
                ).model_dump(mode="json")
            except ValidationError:
                status = "authority_changed"
            else:
                evaluated = evaluate_purchase(
                    r["request"],
                    r["snapshot"],
                    policy["rules"],
                    authority,
                    [x["authority"] for x in approvers],
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
    elif status in ("expired", "superseded", "policy_changed", "authority_changed"):
        action = {"type": "request_fresh_proposal", "tool": "prepare_order"}
    elif status == "rejected" or r["policy_outcome"] == "denied":
        action = {"type": "stop"}
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
        "current_revision": p["current_revision"],
        "committed_revision": order["revision"] if order else None,
        "current_proposal_url": f"{settings().public_base_url}/purchases/{p['id']}",
        "policy_version": r["policy_version"],
        "policy_outcome": r["policy_outcome"],
        "recipe_basis": "saved_recipe" if r["request"].get("recipe_plan_id") else "free_form",
        "approval_status": status,
        "order_status": "accepted_mock" if committed else "not_placed",
        "reasons": r["reasons"],
        "expires_at": r["expires_at"],
        "next_action": action,
        "approval_id": str(a["id"]) if a else None,
        "approval_url": f"{settings().public_base_url}/approvals/{a['id']}" if a else None,
        "order_id": str(order["id"]) if committed else None,
        "buyer_id": buyer["id"],
        "agent_id": p["agent_id"],
        "request": r["request"],
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


def get_proposal(identity, pid):
    with connection() as c:
        return render(c, *proposal(c, pid, identity), identity)


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


def prepare_order(identity, request: PrepareRequest, connector):
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
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
          a.fingerprint AS approval_fingerprint,i.authority AS agent_authority,i.active AS agent_active
          FROM proposals p JOIN approvals a ON a.proposal_id=p.id AND a.revision=p.current_revision
          JOIN proposal_revisions r ON r.proposal_id=p.id AND r.revision=p.current_revision
          JOIN buyers b ON b.id=p.buyer_id
          JOIN identities i ON i.id=p.agent_id AND i.buyer_id=p.buyer_id
          WHERE p.buyer_id=%s AND a.status='pending' AND p.order_id IS NULL AND r.expires_at>%s AND r.policy_version=b.current_policy
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
                        "authority": row["agent_authority"],
                        "active": row["agent_active"],
                    },
                    history=histories[row["id"]],
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


def prior_result(c, identity, request):
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
        purchase = PurchaseRequest.model_validate(r["request"])
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
            actor["authority"],
            [x["authority"] for x in approvers],
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
        # Internal agents can prepare, but a model can never authorize a purchase.
        if c.execute(
            "SELECT 1 FROM internal_agents WHERE identity_id=%s", (identity["id"],)
        ).fetchone():
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
