"""Every purchasing reason carries a `kind` the card reads (owner Q-134 a, 2026-11-15).

blocker    = nothing the customer can approve: severity denied or unresolved (the basket cannot be confirmed)
approvable = severity exception: the customer's own confirm can cover it when their authority lists it
note       = severity warning: shown, blocks nothing
The kind is derived from the severity (one rule), present on every proposal payload, and never changes
whether a basket can be confirmed.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from aimo import auth
from aimo.schemas import PrepareRequest, Reason


@pytest.mark.parametrize(
    "severity, kind",
    [
        ("denied", "blocker"),
        ("unresolved", "blocker"),
        ("exception", "approvable"),
        ("warning", "note"),
    ],
)
def test_the_kind_follows_the_severity(severity, kind):
    reason = Reason(code="X", message="m", severity=severity)
    assert reason.kind == kind
    assert reason.model_dump(mode="json")["kind"] == kind


def test_a_kind_already_present_round_trips():
    first = Reason(code="X", message="m", severity="exception")
    again = Reason.model_validate(first.model_dump(mode="json"))
    assert again.kind == "approvable"


def prepare(service, buyer, lines):
    request = PrepareRequest.model_validate(
        {
            "request_id": "kinds",
            "idempotency_key": str(uuid4()),
            "destination": "hotel-helsinki",
            "delivery_date": str(date.today() + timedelta(days=2)),
            "lines": lines,
        }
    )
    return service.prepare_order(auth.internal_agent(buyer), request)


def test_every_reason_of_a_prepared_proposal_has_its_kind(service, buyer):
    # 465039: a pack with no structured volume (unresolved) ordered in litres; 460675: variable weight
    proposal = prepare(
        service,
        buyer,
        [
            {"product_id": "465039", "amount": "2", "unit": "L"},
            {"product_id": "460675", "amount": "3", "unit": "KG"},
        ],
    )
    kinds = {r["code"]: r["kind"] for r in proposal["reasons"]}
    assert kinds["QUANTITY_UNRESOLVED"] == "blocker" and kinds["TOTAL_UNRESOLVED"] == "blocker"
    assert kinds["VARIABLE_WEIGHT_UNRESOLVED"] == "note"
    assert all("kind" in r for r in proposal["reasons"])
    assert proposal["policy_outcome"] == "needs_resolution"


def test_an_approvable_exception_has_the_kind_approvable(service, buyer):
    # 464306 (in scope) with an amount that is not a whole pack: overbuy, approvable by the customer
    proposal = prepare(service, buyer, [{"product_id": "464306", "amount": "2.5", "unit": "L"}])
    kinds = {r["code"]: r["kind"] for r in proposal["reasons"]}
    assert kinds.get("OVERBUY_REQUIRES_APPROVAL") == "approvable"
    assert proposal["policy_outcome"] == "approval_required"
