"""`reason_classes` on the proposal: one class per reason code, for the card (Q-134 d).

Additive and derived: it never decides anything (the outcome comes from approval_policy). The class
is blocker (unresolved or denied: data or the request must change), exception (the customer's own
confirmation can cover it), warning (blocks nothing) or expired (the cutoff has passed, so the basket
is stale and can only be prepared again).
"""

from datetime import timedelta

from aimo import approval_workflow as workflow
from aimo.db import now
from aimo.schemas import PrepareRequest, ProposalResponse


def classes_of(proposal):
    return proposal["reason_classes"]


def test_an_approvable_basket_classes_its_exceptions(service, agent, mission):
    p = service.prepare_order(agent, mission)
    assert p["policy_outcome"] == "approval_required"
    classes = classes_of(p)
    assert classes["SUBSTITUTION_REQUIRES_APPROVAL"] == "exception"
    assert set(classes) == {r["code"] for r in p["reasons"]}
    assert set(classes.values()) <= {"blocker", "exception", "warning", "expired"}
    ProposalResponse.model_validate(p)  # the public contract carries the field


def test_an_unresolved_basket_classes_its_blockers(service, agent, request_data):
    request_data["lines"] = [{"product_id": "465039", "amount": "1", "unit": "boxes"}]
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "needs_resolution"
    unresolved = {r["code"] for r in p["reasons"] if r["severity"] == "unresolved"}
    assert unresolved
    assert all(classes_of(p)[code] == "blocker" for code in unresolved)


def test_a_denied_reason_is_a_blocker(service, agent, request_data):
    request_data["destination"] = "forbidden"
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "denied"
    assert classes_of(p)["DESTINATION_NOT_ALLOWED"] == "blocker"


def test_a_warning_stays_a_warning():
    reasons = [
        dict(code="VARIABLE_WEIGHT_UNRESOLVED", message="m", product_id="1", severity="warning")
    ]
    assert workflow.reason_classes(reasons, "pending") == {"VARIABLE_WEIGHT_UNRESOLVED": "warning"}


def test_a_passed_cutoff_is_expired_once_the_basket_is_expired():
    reasons = [
        dict(code="CUTOFF_PASSED", message="m", product_id="1", severity="unresolved"),
        dict(code="UNVERIFIED_STOCK", message="m", product_id="1", severity="unresolved"),
    ]
    assert workflow.reason_classes(reasons, "expired") == {
        "CUTOFF_PASSED": "expired",
        "UNVERIFIED_STOCK": "blocker",
    }
    assert workflow.reason_classes(reasons, "pending")["CUTOFF_PASSED"] == "blocker"


def test_the_same_code_with_two_severities_keeps_the_most_serious_class():
    reasons = [
        dict(code="X", message="m", product_id="1", severity="warning"),
        dict(code="X", message="m", product_id="2", severity="unresolved"),
    ]
    assert workflow.reason_classes(reasons, "pending") == {"X": "blocker"}


def test_a_time_expired_basket_renders_the_classes_it_has(service, agent, mission, monkeypatch):
    p = service.prepare_order(agent, mission)
    monkeypatch.setattr(workflow, "now", lambda: now() + timedelta(hours=1))
    later = service.get_proposal(agent, p["proposal_id"])
    assert later["approval_status"] == "expired"
    assert later["reason_classes"] == p["reason_classes"]
