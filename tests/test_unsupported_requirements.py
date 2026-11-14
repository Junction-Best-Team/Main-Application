"""JNP3-POL-009, unsupported half: a requirement the system cannot verify blocks readiness.

The catalog can verify two dietary requirements (lactose-free, milk-free). Anything else the
customer states (for example gluten-free) was a 422 at the tool boundary, which fails closed
but never reaches the buyer as a named reason. `Requirements.unsupported` is the sanctioned way
to carry it: every entry becomes an unresolved `REQUIREMENT_UNSUPPORTED` reason, so the basket is
`needs_resolution` and cannot be committed. Raw unknown keys are still rejected.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from aimo.approval_policy import evaluate_purchase
from aimo.db import Problem
from aimo.schemas import CommitRequest, PrepareRequest, Requirements

RULES = {
    "currency": "EUR",
    "destinations": ["hotel"],
    "substitution": "requires_approval",
    "overbuy": "requires_approval",
    "whole_sales_units": True,
    "approved_product_ids": ["X"],
}
APPROVER = {"currency": "EUR", "max_gross": "5000", "exceptions": ["substitution", "overbuy"]}


def run(unsupported=None, **changes):
    request = {
        "destination": "hotel",
        "lines": [{"product_id": "X"}],
        "requirements": {"lactose_free": False, "milk_free": False}
        | ({"unsupported": unsupported} if unsupported is not None else {}),
    } | changes
    snapshot = {
        "reasons": [],
        "currency": "EUR",
        "gross_total": "10.00",
        "lines": [{"quantity": {"excess": "0"}}],
    }
    return evaluate_purchase(request, snapshot, RULES, [APPROVER])


def codes(result):
    return [r["code"] for r in result["reasons"]]


def test_no_unsupported_requirement_is_ready():
    assert run(None)["policy_outcome"] == "ready_to_commit"
    assert run([])["policy_outcome"] == "ready_to_commit"


def test_one_unsupported_requirement_needs_resolution_and_is_named():
    result = run(["gluten-free"])
    assert result["policy_outcome"] == "needs_resolution"
    reason = next(r for r in result["reasons"] if r["code"] == "REQUIREMENT_UNSUPPORTED")
    assert reason["severity"] == "unresolved" and "gluten-free" in reason["message"]
    assert result["required_exceptions"] == []  # no approval can repair an unverifiable requirement


def test_each_unsupported_requirement_gets_its_own_reason():
    result = run(["gluten-free", "halal"])
    assert codes(result).count("REQUIREMENT_UNSUPPORTED") == 2
    assert result["policy_outcome"] == "needs_resolution"


def test_a_denial_still_wins_over_an_unsupported_requirement():
    result = run(["gluten-free"], destination="elsewhere")
    assert result["policy_outcome"] == "denied"
    assert "REQUIREMENT_UNSUPPORTED" in codes(result)


def test_supported_requirements_are_unaffected():
    request = {"lactose_free": True, "milk_free": True, "unsupported": []}
    assert Requirements.model_validate(request).unsupported == []


def test_the_field_is_bounded():
    with pytest.raises(ValidationError):
        Requirements(unsupported=["x"] * 11)
    with pytest.raises(ValidationError):
        Requirements(unsupported=["y" * 81])
    with pytest.raises(ValidationError):
        Requirements(unsupported=[""])


def test_an_unknown_dietary_key_is_still_rejected_at_the_boundary():
    with pytest.raises(ValidationError):
        Requirements.model_validate({"gluten_free": True})


def test_service_prepare_with_an_unsupported_requirement_cannot_commit(
    service, agent, request_data, confirm_terms
):
    request_data["requirements"] = {"lactose_free": True, "unsupported": ["gluten-free"]}
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "needs_resolution" and p["approval_id"] is None
    assert "REQUIREMENT_UNSUPPORTED" in {r["code"] for r in p["reasons"]}
    assert p["next_action"]["type"] == "revise_request"
    confirm_terms(p)
    with pytest.raises(Problem) as error:
        service.commit_order(
            agent,
            CommitRequest(
                proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4())
            ),
        )
    assert error.value.code == "COMMIT_BLOCKED"


def test_service_without_the_field_is_unchanged(service, agent, request_data):
    p = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert p["policy_outcome"] == "ready_to_commit"
    assert "REQUIREMENT_UNSUPPORTED" not in {r["code"] for r in p["reasons"]}
