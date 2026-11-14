"""WS-C policy rule matrix (JNP3-POL-002/003/004/006/009).

Pure-function cases call approval_policy.evaluate_purchase directly; the last
section drives the same rules through Service. Fixture mode only.
"""

from datetime import date, timedelta
from itertools import product
from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo.approval_policy import evaluate_purchase
from aimo.db import Problem, connection, js
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest

FOUR = {"denied", "needs_resolution", "approval_required", "ready_to_commit"}
APPROVER = {"currency": "EUR", "max_gross": "5000", "exceptions": ["substitution", "overbuy"]}


def rules(**changes):
    base = {
        "currency": "EUR",
        "destinations": ["hotel"],
        "substitution": "requires_approval",
        "overbuy": "requires_approval",
        "whole_sales_units": True,
        "approved_product_ids": ["X"],
    }
    base.update(changes)
    return {k: v for k, v in base.items() if v != "__absent__"}


def request(*product_ids, **changes):
    base = {
        "destination": "hotel",
        "lines": [{"product_id": p} for p in (product_ids or ("X",))],
    }
    return base | changes


def snapshot(total="10.00", excess="0", reasons=(), currency="EUR", lines=1):
    return {
        "reasons": list(reasons),
        "currency": currency,
        "gross_total": total,
        "lines": [{"quantity": {"excess": excess}} for _ in range(lines)],
    }


def run(req=None, snap=None, rule=None, approvers=(APPROVER,), **extra):
    return evaluate_purchase(
        req or request(),
        snap or snapshot(),
        rule if rule is not None else rules(),
        list(approvers),
        **extra,
    )


def codes(result):
    return [r["code"] for r in result["reasons"]]


# --- POL-002: every duty in the policy words maps to a reason code --------------


@pytest.mark.parametrize(
    "case,args,code,severity,outcome",
    [
        (
            "destination",
            dict(req=request(destination="elsewhere")),
            "DESTINATION_NOT_ALLOWED",
            "denied",
            "denied",
        ),
        (
            "hard budget",
            dict(req=request(budget_gross="9.99")),
            "HARD_BUDGET_EXCEEDED",
            "denied",
            "denied",
        ),
        (
            "currency unresolved",
            dict(snap=snapshot(currency=None, total=None)),
            "CURRENCY_UNRESOLVED",
            "unresolved",
            "needs_resolution",
        ),
        (
            "currency outside authority",
            dict(snap=snapshot(currency="USD")),
            "CURRENCY_NOT_ALLOWED",
            "denied",
            "denied",
        ),
        (
            "substitution forbidden",
            dict(req=request("Y"), rule=rules(substitution="forbidden")),
            "SUBSTITUTION_FORBIDDEN",
            "denied",
            "denied",
        ),
        (
            "substitution declared",
            dict(
                req=request(lines=[{"product_id": "X", "substitutes_for": "Z"}]),
                rule=rules(substitution="forbidden"),
            ),
            "SUBSTITUTION_FORBIDDEN",
            "denied",
            "denied",
        ),
        (
            "substitution needs approval",
            dict(req=request("Y")),
            "SUBSTITUTION_REQUIRES_APPROVAL",
            "exception",
            "approval_required",
        ),
        (
            "overbuy forbidden",
            dict(snap=snapshot(excess="1"), rule=rules(overbuy="forbidden")),
            "OVERBUY_FORBIDDEN",
            "denied",
            "denied",
        ),
        (
            "overbuy refused by request",
            dict(snap=snapshot(excess="1"), req=request(allow_overbuy=False)),
            "OVERBUY_FORBIDDEN",
            "denied",
            "denied",
        ),
        (
            "overbuy needs approval",
            dict(snap=snapshot(excess="1")),
            "OVERBUY_REQUIRES_APPROVAL",
            "exception",
            "approval_required",
        ),
        (
            "no approver covers it",
            dict(snap=snapshot(total="6000.00")),
            "NO_ELIGIBLE_APPROVER",
            "unresolved",
            "needs_resolution",
        ),
        (
            "approver lacks exception",
            dict(req=request("Y"), approvers=[{**APPROVER, "exceptions": ["overbuy"]}]),
            "NO_ELIGIBLE_APPROVER",
            "unresolved",
            "needs_resolution",
        ),
        ("missing rules", dict(rule={}), "MISSING_AUTHORITY", "unresolved", "needs_resolution"),
        (
            "no approver at all",
            dict(approvers=()),
            "NO_ELIGIBLE_APPROVER",
            "unresolved",
            "needs_resolution",
        ),
        (
            "approver in another currency",
            dict(approvers=[{**APPROVER, "currency": "SEK"}]),
            "NO_ELIGIBLE_APPROVER",
            "unresolved",
            "needs_resolution",
        ),
    ],
)
def test_each_policy_duty_has_a_reason_code(case, args, code, severity, outcome):
    result = run(**args)
    assert code in codes(result), (case, codes(result))
    matching = [r for r in result["reasons"] if r["code"] == code]
    assert all(r["severity"] == severity for r in matching)
    assert result["policy_outcome"] == outcome


def test_dietary_evidence_enters_policy_through_snapshot_reasons():
    """Dietary reasons come from catalog.requirement_reasons; the policy must keep them."""
    unresolved = {
        "code": "MILK_FREE_UNVERIFIED",
        "message": "m",
        "product_id": "X",
        "severity": "unresolved",
    }
    denied = {
        "code": "MILK_REQUIREMENT_VIOLATED",
        "message": "m",
        "product_id": "X",
        "severity": "denied",
    }
    assert run(snap=snapshot(reasons=[unresolved]))["policy_outcome"] == "needs_resolution"
    assert run(snap=snapshot(reasons=[denied]))["policy_outcome"] == "denied"
    assert run(snap=snapshot(reasons=[unresolved, denied]))["policy_outcome"] == "denied"


def test_clean_request_is_ready_to_commit():
    result = run()
    assert result == {"policy_outcome": "ready_to_commit", "reasons": [], "required_exceptions": []}


# --- POL-003: exactly one of four outcomes, with fixed precedence ---------------


def test_outcome_is_always_one_of_four_with_fixed_precedence():
    severities = ["denied", "unresolved", "exception"]
    grid = product(
        [None, ["X"], []],  # scope: missing, matching, empty
        ["allowed", "requires_approval", "forbidden"],
        ["request-ok", "request-outside"],
        ["1.00", "1500.01", "6000.00", None],
        [None, "denied", "unresolved"],  # injected snapshot reason severity
        [True, False],
    )
    for scope, substitution, outside, total, injected, allow in grid:
        rule = rules(
            approved_product_ids=scope if scope is not None else "__absent__",
            substitution=substitution,
        )
        req = request("Y" if outside == "request-outside" else "X", allow_substitution=allow)
        injected_reasons = (
            [{"code": "INJECTED", "message": "m", "product_id": None, "severity": injected}]
            if injected
            else []
        )
        result = run(req=req, snap=snapshot(total=total, reasons=injected_reasons), rule=rule)
        severity_set = {r["severity"] for r in result["reasons"]}
        assert result["policy_outcome"] in FOUR
        expected = (
            "denied"
            if "denied" in severity_set
            else "needs_resolution"
            if "unresolved" in severity_set
            else "approval_required"
            if result["required_exceptions"]
            else "ready_to_commit"
        )
        assert result["policy_outcome"] == expected
        assert set(severity_set) <= set(severities)


# --- POL-004: missing trusted scope always blocks -------------------------------


@pytest.mark.parametrize("substitution", ["allowed", "requires_approval", "forbidden"])
@pytest.mark.parametrize("allow_substitution", [True, False])
def test_missing_scope_never_ready_to_commit(substitution, allow_substitution):
    result = run(
        req=request(allow_substitution=allow_substitution),
        rule=rules(approved_product_ids="__absent__", substitution=substitution),
    )
    assert "PRODUCT_SCOPE_UNCONFIGURED" in codes(result)
    assert result["policy_outcome"] in ("needs_resolution", "denied")
    assert result["policy_outcome"] != "ready_to_commit"


def test_missing_scope_reason_is_unresolved_and_unrepaired_by_approval():
    result = run(rule=rules(approved_product_ids="__absent__", substitution="allowed"))
    reason = next(r for r in result["reasons"] if r["code"] == "PRODUCT_SCOPE_UNCONFIGURED")
    assert reason["severity"] == "unresolved"
    assert result["policy_outcome"] == "needs_resolution"
    assert result["required_exceptions"] == []  # no approver can repair it


def test_explicit_none_scope_also_blocks():
    result = run(rule=rules(approved_product_ids=None, substitution="allowed"))
    assert result["policy_outcome"] == "needs_resolution"


def test_empty_scope_is_configured_but_approves_nothing():
    """[] is a configured list: every product is outside it and is judged as a substitution."""
    result = run(rule=rules(approved_product_ids=[], substitution="requires_approval"))
    assert "PRODUCT_SCOPE_UNCONFIGURED" not in codes(result)
    assert result["policy_outcome"] == "approval_required"
    assert result["required_exceptions"] == ["substitution"]
    forbidden = run(rule=rules(approved_product_ids=[], substitution="forbidden"))
    assert forbidden["policy_outcome"] == "denied"


# --- POL-006: outside-scope products ---------------------------------------------


def test_outside_scope_product_follows_the_substitution_rule():
    outside = request("Y")
    assert run(req=outside, rule=rules(substitution="forbidden"))["policy_outcome"] == "denied"
    needs = run(req=outside, rule=rules(substitution="requires_approval"))
    assert needs["policy_outcome"] == "approval_required"
    assert needs["required_exceptions"] == ["substitution"]
    assert (
        run(req=outside, rule=rules(substitution="forbidden"), approvers=())["policy_outcome"]
        == "denied"
    )


def test_inside_scope_product_needs_no_substitution_exception():
    result = run(req=request("X"), rule=rules(substitution="forbidden"))
    assert result["policy_outcome"] == "ready_to_commit"
    assert result["required_exceptions"] == []


def test_declared_substitution_is_judged_even_inside_scope():
    declared = request(lines=[{"product_id": "X", "substitutes_for": "Z"}])
    assert run(req=declared, rule=rules(substitution="forbidden"))["policy_outcome"] == "denied"
    assert run(req=declared)["required_exceptions"] == ["substitution"]


def test_allowed_substitution_passes_but_leaves_an_audit_reason():
    """Owner decision 2026-11-14: 'allowed' counts as a permitted exception, with a recorded reason."""
    result = run(req=request("Y", "X"), rule=rules(substitution="allowed"))
    assert result["policy_outcome"] == "ready_to_commit"
    assert result["required_exceptions"] == []
    recorded = [r for r in result["reasons"] if r["code"] == "SUBSTITUTION_ALLOWED_BY_POLICY"]
    assert [r["product_id"] for r in recorded] == ["Y"]  # only the outside-scope line
    assert recorded[0]["severity"] == "exception"


def test_allowed_substitution_reason_covers_declared_substitution_too():
    declared = request(lines=[{"product_id": "X", "substitutes_for": "Z"}])
    result = run(req=declared, rule=rules(substitution="allowed"))
    assert result["policy_outcome"] == "ready_to_commit"
    assert [
        r["product_id"] for r in result["reasons"] if r["code"] == "SUBSTITUTION_ALLOWED_BY_POLICY"
    ] == ["X"]


def test_allowed_substitution_with_a_request_refusal_is_still_denied():
    result = run(req=request("Y", allow_substitution=False), rule=rules(substitution="allowed"))
    assert result["policy_outcome"] == "denied"


def test_in_scope_product_under_allowed_rule_records_no_reason():
    assert run(req=request("X"), rule=rules(substitution="allowed"))["reasons"] == []


# --- POL-009: no ready_to_commit with an unresolved or denied reason --------------

SNAPSHOT_REASONS = [
    ("QUANTITY_UNRESOLVED", "unresolved"),
    ("VARIABLE_WEIGHT_UNRESOLVED", "unresolved"),
    ("TOTAL_UNRESOLVED", "unresolved"),
    ("DEPOSIT_UNRESOLVED", "unresolved"),
    ("PRODUCT_UNKNOWN", "unresolved"),
    ("INSUFFICIENT_STOCK", "unresolved"),
    ("DIETARY_EVIDENCE_CONFLICT", "unresolved"),
    ("LACTOSE_FREE_UNVERIFIED", "unresolved"),
    ("MILK_FREE_UNVERIFIED", "unresolved"),
    ("DELIVERY_UNRESOLVED", "unresolved"),
    ("PRODUCT_DELETED", "denied"),
    ("DELIVERY_IN_PAST", "denied"),
    ("MILK_REQUIREMENT_VIOLATED", "denied"),
]


@pytest.mark.parametrize("code,severity", SNAPSHOT_REASONS)
def test_any_unresolved_or_denied_snapshot_reason_blocks_readiness(code, severity):
    reason = {"code": code, "message": "m", "product_id": "X", "severity": severity}
    result = run(snap=snapshot(reasons=[reason]))
    assert result["policy_outcome"] == ("denied" if severity == "denied" else "needs_resolution")
    assert code in codes(result)


def test_unknown_total_never_reaches_ready_to_commit():
    """Owner decision (Q-30): the guard lives inside evaluate_purchase, not only in its caller."""
    result = run(snap=snapshot(total=None))
    assert result["policy_outcome"] == "needs_resolution"
    reason = next(r for r in result["reasons"] if r["code"] == "TOTAL_UNRESOLVED")
    assert reason["severity"] == "unresolved"
    assert result["required_exceptions"] == []


def test_unknown_total_reason_is_not_duplicated_when_the_snapshot_already_has_it():
    known = {
        "code": "TOTAL_UNRESOLVED",
        "message": "m",
        "product_id": None,
        "severity": "unresolved",
    }
    result = run(snap=snapshot(total=None, reasons=[known]))
    assert codes(result).count("TOTAL_UNRESOLVED") == 1
    assert result["policy_outcome"] == "needs_resolution"


def test_unknown_total_does_not_hide_a_denial():
    result = run(req=request(destination="elsewhere"), snap=snapshot(total=None))
    assert result["policy_outcome"] == "denied"
    assert "TOTAL_UNRESOLVED" in codes(result)


# --- Service level: same rules through prepare, commit and audit ------------------


def set_policy(**changes):
    with connection() as c:
        buyer = c.execute("SELECT * FROM buyers WHERE id='demo-hotel' FOR UPDATE").fetchone()
        row = c.execute(
            "SELECT * FROM policies WHERE buyer_id='demo-hotel' AND version=%s",
            (buyer["current_policy"],),
        ).fetchone()
        merged = {k: v for k, v in (row["rules"] | changes).items() if v != "__absent__"}
        version = buyer["current_policy"] + 1
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',%s,%s)",
            (version, js(merged)),
        )
        c.execute("UPDATE buyers SET current_policy=%s WHERE id='demo-hotel'", (version,))


def commit(p):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )


@pytest.mark.parametrize("substitution", ["allowed", "requires_approval", "forbidden"])
def test_service_blocks_commit_when_scope_is_missing(service, agent, request_data, substitution):
    set_policy(approved_product_ids="__absent__", substitution=substitution)
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "needs_resolution" and p["approval_id"] is None
    assert "PRODUCT_SCOPE_UNCONFIGURED" in {r["code"] for r in p["reasons"]}
    with pytest.raises(Problem) as error:
        service.commit_order(agent, commit(p))
    assert error.value.code == "COMMIT_BLOCKED"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


def test_service_allowed_substitution_commits_and_the_reason_reaches_the_audit_log(
    service, agent, request_data, confirm_terms
):
    set_policy(substitution="allowed")
    request_data["lines"] = [{"product_id": "464398", "amount": "10", "unit": "L"}]
    request_data["delivery_date"] = str(date.today() + timedelta(days=2))
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "ready_to_commit"
    assert "SUBSTITUTION_ALLOWED_BY_POLICY" in {r["code"] for r in p["reasons"]}
    confirm_terms(p)
    receipt = service.commit_order(agent, commit(p))
    assert receipt["status"] == "accepted_mock"
    with connection() as c:
        detail = c.execute(
            "SELECT detail FROM audit_events WHERE proposal_id=%s AND event='proposal_prepared'",
            (p["proposal_id"],),
        ).fetchone()["detail"]
    assert "SUBSTITUTION_ALLOWED_BY_POLICY" in {r["code"] for r in detail["reasons"]}


def test_service_requires_approval_substitution_still_needs_a_decision(
    service, agent, buyer, request_data, confirm_terms
):
    set_policy(substitution="requires_approval")
    request_data["lines"] = [{"product_id": "464398", "amount": "10", "unit": "L"}]
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "approval_required"
    with pytest.raises(Problem) as error:
        service.commit_order(agent, commit(p))
    assert error.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"  # WS-D T1: every agent role
    confirm_terms(p)
    with pytest.raises(Problem) as error:
        service.commit_order(agent, commit(p))
    assert error.value.code == "APPROVAL_REQUIRED"
    workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=1, decision="approve")
    )
    assert service.commit_order(agent, commit(p))["status"] == "accepted_mock"


# --- POL-008: an unconfirmed assumption never loosens a hard limit (waits for provenance) -----


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason="POL-008 is not enforceable yet: no per-constraint provenance exists. Constraint sources "
    "will be stored as a JSON field on the request record (owner Q-53, no migration); person 2's "
    "#92 and person 1's extraction/persistence are still pending. evaluate_purchase has no "
    "trusted `constraints` input; see evidence/ws-c/pol-008-design.md.",
)
def test_unconfirmed_assumption_never_loosens_hard_limits():
    """Target behaviour. `constraints` is a SERVER-supplied record (never a model argument) of what
    the customer stated, each entry {name, value, source, confirmed}; the request carries the
    model's values. The effective limit is the stricter of the two; a looser request value is a
    named reason, never a silent relaxation."""
    stated_budget = {
        "name": "budget_gross",
        "value": "50.00",
        "source": "user_request",
        "confirmed": True,
    }
    stated_milk_free = {
        "name": "milk_free",
        "value": True,
        "source": "user_request",
        "confirmed": True,
    }
    assumed_loose_budget = {
        "name": "budget_gross",
        "value": "500.00",
        "source": "stated_assumption",
        "confirmed": False,
    }
    over_stated = snapshot(total="100.00")

    # (a) a looser unconfirmed budget cannot lift the customer's stated budget of 50
    result = run(
        req=request(budget_gross="500.00"),
        snap=over_stated,
        constraints=[stated_budget, assumed_loose_budget],
    )
    assert result["policy_outcome"] == "denied" and "HARD_BUDGET_EXCEEDED" in codes(result)

    # (b) dropping a stated dietary requirement from the request is a named reason, not a pass
    dropped = run(
        req=request(requirements={"milk_free": False}),
        constraints=[stated_milk_free],
    )
    assert dropped["policy_outcome"] == "needs_resolution"
    assert "CONSTRAINT_LOOSENED" in codes(dropped)

    # (c) a stricter assumption is allowed and still enforced
    stricter = {
        "name": "budget_gross",
        "value": "40.00",
        "source": "stated_assumption",
        "confirmed": False,
    }
    strict_result = run(
        req=request(budget_gross="40.00"),
        snap=snapshot(total="30.00"),
        constraints=[stated_budget, stricter],
    )
    assert strict_result["policy_outcome"] == "ready_to_commit"
    assert (
        run(
            req=request(budget_gross="40.00"),
            snap=over_stated,
            constraints=[stated_budget, stricter],
        )["policy_outcome"]
        == "denied"
    )
