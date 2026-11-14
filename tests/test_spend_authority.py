"""JNP3-POL-013 (Draft, owner decision Q-35): spend limits apply only to human approvers and to the
request's hard budget. The agent identity holds no spend authority and there is no autonomous limit.

Built behaviour; no test is xfail. Tests named `approver_coverage` are POL-014 (owner decision Q-37,
wording Draft): NO_ELIGIBLE_APPROVER whenever the total is known and no active approver covers it. Pure cases call
approval_policy.evaluate_purchase; the rest drive Service and conversations against PostgreSQL.
Fixture upstream only.
"""

import inspect
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aimo import auth, conversations
from aimo.approval_policy import evaluate_purchase
from aimo.db import Problem, connection, js
from aimo.schemas import ApproverAuthority, CommitRequest, PolicyRules, PrepareRequest

# Approver as seeded after Q-35: a maximum amount and the two remaining exceptions.
APPROVER = {"currency": "EUR", "max_gross": "5000", "exceptions": ["substitution", "overbuy"]}
# Legacy shapes that stored rows may still carry.
LEGACY_APPROVER = {**APPROVER, "exceptions": ["spend", "substitution", "overbuy"]}
LEGACY_AGENT = {"currency": "EUR", "autonomous_limit": "1500.00"}
STORED_AGENT_SHAPES = [
    {},  # as seeded
    LEGACY_AGENT,
    {"autonomous_limit": "0"},
    {"autonomous_limit": "999999"},
]


def rules(**changes):
    """Policy rules without autonomous_limit (the target shape)."""
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


def snapshot(total="10.00", excess="0", currency="EUR"):
    return {
        "reasons": [],
        "currency": currency,
        "gross_total": total,
        "lines": [{"quantity": {"excess": excess}}],
    }


def run(req=None, snap=None, rule=None, approvers=(APPROVER,)):
    return evaluate_purchase(
        req or request(),
        snap or snapshot(),
        rule if rule is not None else rules(),
        list(approvers),
    )


def codes(result):
    return [r["code"] for r in result["reasons"]]


def no_old_spend_model(result):
    assert "AUTONOMOUS_LIMIT_EXCEEDED" not in codes(result), codes(result)
    assert "spend" not in result["required_exceptions"], result["required_exceptions"]


# --- 1. Totals against the approver's maximum --------------------------------------


@pytest.mark.parametrize("total", ["1.00", "1500.01", "5000.00"])
def test_totals_within_the_approver_maximum_are_ready_without_exception(total):
    result = run(snap=snapshot(total=total))
    no_old_spend_model(result)
    assert result["policy_outcome"] == "ready_to_commit"
    assert result["reasons"] == []
    assert result["required_exceptions"] == []


@pytest.mark.parametrize("total", ["5000.01", "100000.00"])
def test_total_above_every_approver_maximum_needs_resolution(total):
    result = run(snap=snapshot(total=total))
    no_old_spend_model(result)
    assert result["policy_outcome"] == "needs_resolution"
    assert codes(result) == ["NO_ELIGIBLE_APPROVER"]
    reason = result["reasons"][0]
    assert reason["severity"] == "unresolved"
    assert result["required_exceptions"] == []


def test_boundary_total_equal_to_the_maximum_is_ready():
    result = run(snap=snapshot(total="5000.00"), approvers=({**APPROVER, "max_gross": "5000.00"},))
    assert result["policy_outcome"] == "ready_to_commit"
    assert result["reasons"] == []


def test_boundary_total_one_cent_above_the_maximum_needs_resolution():
    result = run(snap=snapshot(total="5000.01"), approvers=({**APPROVER, "max_gross": "5000.00"},))
    assert result["policy_outcome"] == "needs_resolution"
    assert codes(result) == ["NO_ELIGIBLE_APPROVER"]


def test_no_eligible_approver_with_an_exception_in_play_has_no_limit_reason():
    result = run(
        req=request("Y"),  # outside scope: substitution requires approval
        snap=snapshot(total="6000.00"),
    )
    no_old_spend_model(result)
    assert result["policy_outcome"] == "needs_resolution"
    assert "NO_ELIGIBLE_APPROVER" in codes(result)
    assert "SUBSTITUTION_REQUIRES_APPROVAL" in codes(result)
    assert result["required_exceptions"] == ["substitution"]


@pytest.mark.parametrize("total", ["0.01", "1500.01", "5000.00", "5000.01", "100000.00"])
@pytest.mark.parametrize("candidate", ["X", "Y"])
def test_no_spend_exception_or_limit_reason_anywhere(total, candidate):
    no_old_spend_model(run(req=request(candidate), snap=snapshot(total=total)))


def test_unknown_total_adds_no_spend_exception():
    """Holds today and must keep holding: an unknown total skips every spending rule."""
    result = run(snap=snapshot(total=None))
    no_old_spend_model(result)
    assert result["policy_outcome"] == "needs_resolution"


def test_approver_with_two_target_exceptions_covers_a_plain_large_total():
    assert run(snap=snapshot(total="3000.00"))["policy_outcome"] == "ready_to_commit"


def test_legacy_spend_in_an_approver_authority_is_ignored():
    legacy = run(snap=snapshot(total="3000.00"), approvers=(LEGACY_APPROVER,))
    clean = run(snap=snapshot(total="3000.00"), approvers=(APPROVER,))
    assert legacy == clean
    no_old_spend_model(legacy)
    assert legacy["policy_outcome"] == "ready_to_commit"


# --- 2. Approver set: zero, inactive, two, currency -------------------------------


def test_approver_coverage_boundary_maximum_equal_to_total_is_ready():
    result = run(snap=snapshot(total="250.00"), approvers=({**APPROVER, "max_gross": "250.00"},))
    assert result == {"policy_outcome": "ready_to_commit", "reasons": [], "required_exceptions": []}


def test_approver_coverage_one_cent_above_the_maximum_is_needs_resolution():
    result = run(snap=snapshot(total="250.01"), approvers=({**APPROVER, "max_gross": "250.00"},))
    assert result["policy_outcome"] == "needs_resolution"
    assert codes(result) == ["NO_ELIGIBLE_APPROVER"]
    assert result["required_exceptions"] == []


def test_approver_coverage_unknown_total_does_not_add_the_reason():
    result = run(snap=snapshot(total=None), approvers=())
    assert "NO_ELIGIBLE_APPROVER" not in codes(result)
    assert "TOTAL_UNRESOLVED" in codes(result)


def test_approver_coverage_denial_wins_over_no_approver():
    result = run(req=request(destination="elsewhere"), approvers=())
    assert result["policy_outcome"] == "denied"
    assert "NO_ELIGIBLE_APPROVER" in codes(result)


def test_approver_coverage_zero_approvers_is_needs_resolution_without_an_exception():
    result = run(approvers=())
    assert result["policy_outcome"] == "needs_resolution"
    assert codes(result) == ["NO_ELIGIBLE_APPROVER"]
    assert result["required_exceptions"] == []


def test_approver_coverage_zero_or_missing_maximum_covers_nothing():
    zero = {**APPROVER, "max_gross": "0"}
    missing = {"currency": "EUR", "exceptions": ["substitution"]}
    result = run(approvers=(zero, missing))
    no_old_spend_model(result)
    assert result["policy_outcome"] == "needs_resolution"
    assert codes(result) == ["NO_ELIGIBLE_APPROVER"]


def test_approver_coverage_one_small_and_one_large_approver_is_ready():
    small = {**APPROVER, "max_gross": "100"}
    large = {**APPROVER, "max_gross": "9000"}
    result = run(snap=snapshot(total="8000.00"), approvers=(small, large))
    assert result["policy_outcome"] == "ready_to_commit"
    # The small one alone is not enough.
    alone = run(snap=snapshot(total="8000.00"), approvers=(small,))
    assert alone["policy_outcome"] == "needs_resolution"
    assert codes(alone) == ["NO_ELIGIBLE_APPROVER"]


def test_approver_coverage_currency_mismatch_does_not_count():
    result = run(approvers=({**APPROVER, "currency": "USD"},))
    assert result["policy_outcome"] == "needs_resolution"
    assert codes(result) == ["NO_ELIGIBLE_APPROVER"]


# --- 3. The request's hard budget stays --------------------------------------------


def test_hard_budget_equal_to_total_is_not_exceeded():
    result = run(req=request(budget_gross="10.00"), snap=snapshot(total="10.00"))
    assert "HARD_BUDGET_EXCEEDED" not in codes(result)
    assert result["policy_outcome"] != "denied"


def test_hard_budget_one_cent_below_total_is_denied():
    result = run(req=request(budget_gross="9.99"), snap=snapshot(total="10.00"))
    assert "HARD_BUDGET_EXCEEDED" in codes(result)
    assert result["policy_outcome"] == "denied"
    reason = next(r for r in result["reasons"] if r["code"] == "HARD_BUDGET_EXCEEDED")
    assert reason["severity"] == "denied"


def test_request_without_a_budget_compares_nothing():
    result = run(req=request(), snap=snapshot(total="100000.00"))
    assert "HARD_BUDGET_EXCEEDED" not in codes(result)


@pytest.mark.parametrize("budget", ["0.01", "9.99"])
def test_hard_budget_denial_wins_over_a_missing_approver(budget):
    result = run(req=request(budget_gross=budget), snap=snapshot(total="10.00"), approvers=())
    assert result["policy_outcome"] == "denied"


def test_hard_budget_equal_to_total_is_ready_to_commit():
    result = run(req=request(budget_gross="10.00"), snap=snapshot(total="10.00"))
    assert result == {"policy_outcome": "ready_to_commit", "reasons": [], "required_exceptions": []}


# --- 4. The agent's authority is irrelevant -----------------------------------------


def test_evaluate_purchase_takes_no_agent_authority_parameter():
    parameters = list(inspect.signature(evaluate_purchase).parameters)
    assert "authority" not in parameters
    assert parameters == ["request", "snapshot", "rules", "approvers"]


# --- 4b. Same at Service level, with the seeded demo agent -------------------------


def body(p):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )


def comparable(proposal):
    keys = ("policy_outcome", "reasons", "approval_status", "next_action")
    return {k: proposal[k] for k in keys} | {"gross_total": proposal["snapshot"]["gross_total"]}


def prepare_with_agent_authority(service, request_data, authority):
    with connection() as c:
        c.execute("UPDATE identities SET authority=%s WHERE id='demo-agent'", (js(authority),))
        agent = c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()
    request_data["idempotency_key"] = str(uuid4())
    return service.prepare_order(agent, PrepareRequest.model_validate(request_data))


def test_service_result_is_identical_for_every_agent_authority_shape(
    service, request_data, confirm_terms
):
    baseline = comparable(prepare_with_agent_authority(service, request_data, {}))
    assert baseline["policy_outcome"] == "ready_to_commit"
    assert baseline["reasons"] == []
    for shape in STORED_AGENT_SHAPES:
        got = comparable(prepare_with_agent_authority(service, request_data, shape))
        assert got == baseline, shape
    # The next action is part of comparable(); a stored shape never changes who may do what.
    assert baseline["next_action"]


@pytest.mark.parametrize("shape", STORED_AGENT_SHAPES, ids=lambda s: str(s))
def test_service_agent_commits_after_confirmation_whatever_its_stored_authority(
    service, request_data, confirm_terms, shape
):
    p = prepare_with_agent_authority(service, request_data, shape)
    confirm_terms(p)
    with connection() as c:
        agent = c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()
    receipt = service.commit_order(agent, body(p))
    assert receipt["status"] == "accepted_mock"


def test_service_agent_with_empty_authority_can_prepare(service, request_data):
    proposal = prepare_with_agent_authority(service, request_data, {})
    assert proposal["policy_outcome"] == "ready_to_commit"
    assert proposal["reasons"] == []


# --- 4c. The approver maximum bites at prepare time (Service) ----------------------


def set_approver(**authority):
    with connection() as c:
        row = c.execute("SELECT authority FROM identities WHERE id='buyer'").fetchone()
        c.execute(
            "UPDATE identities SET authority=%s WHERE id='buyer'",
            (js(row["authority"] | authority),),
        )


def test_approver_coverage_service_total_above_the_maximum_needs_resolution(
    service, agent, request_data
):
    set_approver(max_gross="0.01")
    proposal = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert proposal["policy_outcome"] == "needs_resolution"
    assert "NO_ELIGIBLE_APPROVER" in {r["code"] for r in proposal["reasons"]}
    assert "AUTONOMOUS_LIMIT_EXCEEDED" not in {r["code"] for r in proposal["reasons"]}


def test_approver_coverage_service_only_approver_inactive_needs_resolution(
    service, agent, request_data
):
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    proposal = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert proposal["policy_outcome"] == "needs_resolution"
    assert "NO_ELIGIBLE_APPROVER" in {r["code"] for r in proposal["reasons"]}


def prepared_total(service, agent, request_data):
    probe = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    request_data["idempotency_key"] = str(uuid4())
    return Decimal(probe["snapshot"]["gross_total"])


def reasons_of(proposal):
    return {r["code"] for r in proposal["reasons"]}


def test_approver_coverage_service_boundary_maximum_equal_to_total_is_ready(
    service, agent, request_data, confirm_terms
):
    total = prepared_total(service, agent, request_data)
    set_approver(max_gross=str(total))
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "ready_to_commit"
    assert p["reasons"] == []
    confirm_terms(p)
    assert service.commit_order(agent, body(p))["status"] == "accepted_mock"


def test_approver_coverage_service_one_cent_above_the_maximum_blocks_commit(
    service, agent, request_data, confirm_terms
):
    total = prepared_total(service, agent, request_data)
    set_approver(max_gross=str(total - Decimal("0.01")))
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "needs_resolution"
    assert reasons_of(p) == {"NO_ELIGIBLE_APPROVER"}
    assert p["approval_id"] is None
    with pytest.raises(Problem) as error:
        service.commit_order(agent, body(p))
    assert error.value.code == "COMMIT_BLOCKED"
    assert order_count() == 0


def test_approver_coverage_service_inactive_approver_does_not_count_next_to_an_active_one(
    service, agent, request_data
):
    with connection() as c:
        c.execute(
            "INSERT INTO identities VALUES('big-approver','demo-hotel','approver',false,'!no-login',%s)",
            (js({"currency": "EUR", "max_gross": "99999", "exceptions": ["substitution"]}),),
        )
    set_approver(max_gross="0.01")  # the only active approver is too small
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "needs_resolution"
    assert reasons_of(p) == {"NO_ELIGIBLE_APPROVER"}


def test_approver_coverage_service_one_small_and_one_large_approver_is_ready(
    service, agent, request_data
):
    set_approver(max_gross="0.01")
    with connection() as c:
        c.execute(
            "INSERT INTO identities VALUES('big-approver','demo-hotel','approver',true,'!no-login',%s)",
            (js({"currency": "EUR", "max_gross": "99999", "exceptions": ["substitution"]}),),
        )
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "ready_to_commit"
    assert p["reasons"] == []


def test_approver_coverage_service_currency_mismatch_does_not_count(service, agent, request_data):
    set_approver(currency="USD")
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "needs_resolution"
    assert reasons_of(p) == {"NO_ELIGIBLE_APPROVER"}


def test_approver_coverage_service_no_approver_at_all_needs_resolution(
    service, agent, request_data
):
    with connection() as c:
        c.execute("DELETE FROM identities WHERE role='approver' AND id<>'buyer'")
        c.execute("UPDATE identities SET active=false WHERE role='approver'")
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "needs_resolution"
    assert reasons_of(p) == {"NO_ELIGIBLE_APPROVER"}


def test_service_hard_budget_boundary_is_unchanged(service, agent, request_data):
    probe = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    total = Decimal(probe["snapshot"]["gross_total"])
    assert total > Decimal("0.01")
    request_data["idempotency_key"] = str(uuid4())
    request_data["budget_gross"] = str(total)
    at = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert "HARD_BUDGET_EXCEEDED" not in {r["code"] for r in at["reasons"]}
    assert at["policy_outcome"] != "denied"
    request_data["idempotency_key"] = str(uuid4())
    request_data["budget_gross"] = str(total - Decimal("0.01"))
    below = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert below["policy_outcome"] == "denied"
    assert "HARD_BUDGET_EXCEEDED" in {r["code"] for r in below["reasons"]}


# --- 5. Confirmation by a human whose maximum is below the total ------------------


def order_count():
    with connection() as c:
        return c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"]


def test_confirm_by_an_approver_below_the_total_gets_approval_scope(service, buyer, request_data):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] in {"ready_to_commit", "approval_required"}
    set_approver(max_gross="0.01")  # lowered after the proposal was prepared
    with connection() as c:
        buyer_low = c.execute("SELECT * FROM identities WHERE id='buyer'").fetchone()
    with pytest.raises(Problem) as error:
        conversations.confirm(buyer_low, p["proposal_id"], body(p), service)
    assert error.value.code == "APPROVAL_SCOPE"
    assert error.value.status == 403
    assert order_count() == 0


def test_confirm_by_an_approver_with_enough_maximum_gets_the_receipt(service, buyer, request_data):
    internal = auth.internal_agent(buyer)
    p = service.prepare_order(internal, PrepareRequest.model_validate(request_data))
    total = Decimal(p["snapshot"]["gross_total"])
    set_approver(max_gross=str(total))  # exactly the total is enough
    with connection() as c:
        buyer_exact = c.execute("SELECT * FROM identities WHERE id='buyer'").fetchone()
    receipt = conversations.confirm(buyer_exact, p["proposal_id"], body(p), service)
    assert receipt["status"] == "accepted_mock"
    assert order_count() == 1


# --- 6. Tolerance of legacy keys; every other unknown key is still rejected -------


def legacy_rules(**changes):
    return rules(autonomous_limit="1500.00", **changes)


def test_policy_rules_without_autonomous_limit_validate():
    PolicyRules.model_validate(rules())


def test_policy_rules_with_the_legacy_key_still_validate():
    PolicyRules.model_validate(legacy_rules())


def test_legacy_policy_key_is_dropped_by_validation():
    model = PolicyRules.model_validate(legacy_rules())
    assert "autonomous_limit" not in model.model_dump()


def test_policy_rules_still_reject_any_other_unknown_key():
    with pytest.raises(ValidationError) as error:
        PolicyRules.model_validate(legacy_rules(bogus_limit="1"))
    assert any(
        e["type"] == "extra_forbidden" and e["loc"] == ("bogus_limit",)
        for e in error.value.errors()
    )


def test_approver_authority_accepts_the_two_target_exceptions():
    ApproverAuthority.model_validate(APPROVER)


def test_approver_authority_tolerates_a_legacy_spend_exception():
    ApproverAuthority.model_validate(LEGACY_APPROVER)


def test_legacy_spend_exception_is_discarded_by_validation():
    model = ApproverAuthority.model_validate(LEGACY_APPROVER)
    assert "spend" not in model.exceptions


@pytest.mark.parametrize(
    "authority",
    [
        {**APPROVER, "autonomous_limit": "1"},
        {**APPROVER, "bogus": 1},
        {**APPROVER, "exceptions": ["teleport"]},
    ],
)
def test_approver_authority_still_rejects_other_unknown_keys_and_values(authority):
    with pytest.raises(ValidationError):
        ApproverAuthority.model_validate(authority)


def test_stored_new_shape_policy_gives_the_same_outcome_as_the_legacy_one(
    service, agent, request_data
):
    legacy = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    with connection() as c:
        buyer = c.execute("SELECT * FROM buyers WHERE id='demo-hotel' FOR UPDATE").fetchone()
        row = c.execute(
            "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=%s",
            (buyer["current_policy"],),
        ).fetchone()
        new = {k: v for k, v in row["rules"].items() if k != "autonomous_limit"}
        version = buyer["current_policy"] + 1
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',%s,%s)",
            (version, js(new)),
        )
        c.execute("UPDATE buyers SET current_policy=%s WHERE id='demo-hotel'", (version,))
    request_data["idempotency_key"] = str(uuid4())
    fresh = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert comparable(fresh) == comparable(legacy)
