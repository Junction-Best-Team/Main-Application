from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from aimo import approval_workflow as workflow
from aimo.cli import seed
from aimo.db import Problem, connection, js, now
from aimo.schemas import CommitRequest, DecisionRequest, PrepareRequest
from aimo.service import Service
from aimo.upstream import FixtureClient


def commit(p, key=None):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=key or str(uuid4())
    )


def decide(buyer, p, decision="approve"):
    return workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=p["revision"], decision=decision)
    )


def expect_code(code, fn):
    with pytest.raises(Problem) as error:
        fn()
    assert error.value.code == code


def test_autonomous_and_idempotent_after_restart(service, agent, request_data):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "ready_to_commit"
    assert p["snapshot"]["gross_total"] == "17.00"
    req = commit(p)
    receipt = service.commit_order(agent, req)
    assert receipt["label"] == "Accepted by demo order service"
    assert receipt["upstream_order_placed"] is False
    assert receipt["next_action"] == {"type": "complete", "tool": "get_order"}
    assert receipt["order_status"] == "accepted_mock"

    # A new service and connection recover the receipt even if upstream is unavailable.
    class Broken:
        def lookup(self, *args):
            raise AssertionError("completed retry must not query upstream")

    assert Service(Broken()).commit_order(agent, req) == receipt
    assert Service().get_order(agent, receipt["order_id"]) == receipt
    assert service.get_proposal(agent, p["proposal_id"])["next_action"]["type"] == "complete"


def test_independent_inbox_and_agent_resume(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    assert p["policy_outcome"] == "approval_required"
    assert p["snapshot"]["gross_total"] == "1700.00"
    assert p["next_action"]["type"] == "wait"
    inbox = workflow.list_approvals(buyer)
    assert inbox["items"][0]["proposal_id"] == p["proposal_id"]
    expect_code("APPROVAL_REQUIRED", lambda: service.commit_order(agent, commit(p)))
    approved = decide(buyer, p)
    assert approved["approval_status"] == "approved"
    assert approved["order_status"] == "not_placed"
    assert decide(buyer, p)["approval_status"] == "approved"
    resumed = Service().get_proposal(agent, p["proposal_id"])
    assert resumed["next_action"]["type"] == "commit"
    assert (
        Service(FixtureClient()).commit_order(agent, commit(resumed))["status"] == "accepted_mock"
    )
    assert service.get_purchase_policy(agent)["rules"]["autonomous_limit"] == "1500.00"


@pytest.mark.parametrize("eligible_approver", [True, False])
def test_reduced_agent_authority_revises_without_policy_change(
    service, agent, buyer, request_data, eligible_approver
):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["snapshot"]["gross_total"] == "17.00"
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id='demo-hotel' FOR UPDATE")
        c.execute(
            "UPDATE identities SET authority=%s WHERE id='demo-agent'",
            (js({"currency": "EUR", "autonomous_limit": "10"}),),
        )
        if not eligible_approver:
            c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    stale = service.get_proposal(agent, p["proposal_id"])
    assert stale["approval_status"] == "authority_changed"
    assert stale["next_action"]["type"] != "commit"
    fresh = service.commit_order(agent, commit(p))
    assert fresh["status"] == "revised" and fresh["revision"] == 2
    assert fresh["policy_version"] == p["policy_version"]
    assert fresh["snapshot"]["gross_total"] == "17.00"
    assert any(r["code"] == "AUTONOMOUS_LIMIT_EXCEEDED" for r in fresh["reasons"])
    expect_code("STALE_REVISION", lambda: service.commit_order(agent, commit(p)))
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM orders").fetchone()["n"] == 0
    resumed = Service().get_proposal(agent, p["proposal_id"])
    if eligible_approver:
        assert resumed["policy_outcome"] == "approval_required"
        assert resumed["approval_status"] == "pending"
        assert resumed["next_action"]["type"] == "wait"
        assert workflow.list_approvals(buyer)["items"][0]["approval_id"] == fresh["approval_id"]
        expect_code("APPROVAL_REQUIRED", lambda: service.commit_order(agent, commit(fresh)))
        decide(buyer, fresh)
        assert service.commit_order(agent, commit(fresh))["status"] == "accepted_mock"
    else:
        assert resumed["policy_outcome"] == "needs_resolution"
        assert resumed["approval_id"] is None
        assert resumed["next_action"]["type"] == "revise_request"
        expect_code("COMMIT_BLOCKED", lambda: service.commit_order(agent, commit(fresh)))


@pytest.mark.parametrize(
    "patch,outcome,code",
    [
        ({"destination": "another-city"}, "denied", "DESTINATION_NOT_ALLOWED"),
        ({"budget_gross": "16.99"}, "denied", "HARD_BUDGET_EXCEEDED"),
        ({"requirements": {"milk_free": True}}, "denied", "MILK_REQUIREMENT_VIOLATED"),
        (
            {"lines": [{"product_id": "464306", "amount": "1000", "unit": "L"}]},
            "needs_resolution",
            "INSUFFICIENT_STOCK",
        ),
        (
            {"lines": [{"product_id": "465039", "amount": "10", "unit": "L"}]},
            "needs_resolution",
            "QUANTITY_UNRESOLVED",
        ),
        (
            {"lines": [{"product_id": "460675", "amount": "12", "unit": "KG"}]},
            "needs_resolution",
            "VARIABLE_WEIGHT_UNRESOLVED",
        ),
        (
            {"lines": [{"product_id": "468044", "amount": "1", "unit": "ST"}]},
            "needs_resolution",
            "DIETARY_EVIDENCE_CONFLICT",
        ),
        (
            {"lines": [{"product_id": "469429", "amount": "1", "unit": "ST"}]},
            "needs_resolution",
            "DIETARY_EVIDENCE_CONFLICT",
        ),
    ],
)
def test_four_outcomes_and_hard_requirements(service, agent, request_data, patch, outcome, code):
    request_data.update(patch)
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == outcome
    assert code in [r["code"] for r in p["reasons"]]
    assert p["approval_id"] is None
    expect_code("COMMIT_BLOCKED", lambda: service.commit_order(agent, commit(p)))


def test_denied_precedes_unknown(service, agent, request_data):
    request_data.update(
        destination="forbidden", lines=[{"product_id": "465039", "amount": "1", "unit": "boxes"}]
    )
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["policy_outcome"] == "denied"
    assert {"DESTINATION_NOT_ALLOWED", "QUANTITY_UNRESOLVED"} <= {r["code"] for r in p["reasons"]}


def test_changed_price_creates_revision_and_invalidates_approval(
    service, connector, agent, buyer, mission
):
    p = service.prepare_order(agent, mission)
    decide(buyer, p)
    connector.price_multiplier = Decimal("1.10")
    result = service.commit_order(agent, commit(p))
    fresh = result
    assert result["status"] == "revised"
    assert fresh["revision"] == 2 and fresh["approval_status"] == "pending"
    assert workflow.approval_detail(buyer, p["approval_id"])["approval_status"] == "superseded"
    expect_code("STALE_REVISION", lambda: decide(buyer, p))
    expect_code("STALE_REVISION", lambda: service.commit_order(agent, commit(p)))
    expect_code("APPROVAL_REQUIRED", lambda: service.commit_order(agent, commit(fresh)))
    decide(buyer, fresh)
    receipt = service.commit_order(agent, commit(fresh))
    assert receipt["status"] == "accepted_mock"
    historical = workflow.approval_detail(buyer, p["approval_id"])
    assert historical["snapshot"]["gross_total"] == "1700.00"
    assert historical["approval_status"] == "superseded"
    assert historical["order_status"] == "not_placed" and historical["order_id"] is None
    assert historical["can_decide"] is False
    assert historical["next_action"]["type"] == "view_current_proposal"
    assert historical["current_revision"] == historical["committed_revision"] == 2
    assert historical["current_proposal_url"].endswith(f"/purchases/{p['proposal_id']}")
    current = service.get_proposal(buyer, p["proposal_id"])
    assert current["snapshot"]["gross_total"] == "1870.00"
    assert current["order_id"] == receipt["order_id"]
    assert current["order_status"] == "accepted_mock"


def test_stock_change_blocks_old_revision(service, connector, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    decide(buyer, p)
    connector.stock["464306"] = "10"
    fresh = service.commit_order(agent, commit(p))
    assert fresh["policy_outcome"] == "needs_resolution"
    assert fresh["approval_id"] is None


def test_rejection_expiry_and_revocation(service, agent, buyer, mission, monkeypatch):
    p = service.prepare_order(agent, mission)
    decide(buyer, p, "reject")
    expect_code("APPROVAL_REJECTED", lambda: service.commit_order(agent, commit(p)))
    expect_code("DECISION_CONFLICT", lambda: decide(buyer, p))
    p2 = service.prepare_order(agent, mission.model_copy(update={"idempotency_key": str(uuid4())}))
    decide(buyer, p2)
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    revised = service.commit_order(agent, commit(p2))
    assert revised["status"] == "revised" and revised["policy_outcome"] == "needs_resolution"
    expect_code("COMMIT_BLOCKED", lambda: service.commit_order(agent, commit(revised)))
    p3 = service.prepare_order(agent, mission.model_copy(update={"idempotency_key": str(uuid4())}))
    monkeypatch.setattr(workflow, "now", lambda: now() + timedelta(hours=1))
    expect_code("PROPOSAL_EXPIRED", lambda: service.commit_order(agent, commit(p3)))
    assert service.get_proposal(agent, p3["proposal_id"])["approval_status"] == "expired"
    rejected = service.get_proposal(agent, p["proposal_id"])
    assert rejected["approval_status"] == "rejected"
    assert rejected["next_action"] == {"type": "stop"}


def test_policy_version_reauthorizes_and_seed_preserves(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    decide(buyer, p)
    with connection() as c:
        c.execute("SELECT id FROM buyers WHERE id='demo-hotel' FOR UPDATE")
        rules = c.execute(
            "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
        ).fetchone()["rules"]
        rules["autonomous_limit"] = "500"
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)", (js(rules),)
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    seed()
    assert service.get_purchase_policy(agent)["policy_version"] == 2
    assert service.get_purchase_policy(agent)["rules"]["autonomous_limit"] == "500"
    assert service.get_proposal(agent, p["proposal_id"])["approval_status"] == "policy_changed"
    fresh = service.commit_order(agent, commit(p))
    assert fresh["policy_version"] == 2 and fresh["approval_status"] == "pending"


@pytest.mark.parametrize("change", ["expiry", "policy"])
def test_denied_direct_order_can_request_fresh_terms(
    service, agent, request_data, monkeypatch, change
):
    from aimo.config import settings

    request_data["destination"] = "new-destination"
    if change == "expiry":
        monkeypatch.setattr(settings(), "proposal_ttl_seconds", -1)
    first = service.prepare_order(agent, PrepareRequest(**request_data))
    assert first["policy_outcome"] == "denied"
    if change == "policy":
        assert first["next_action"]["type"] == "stop"
        with connection() as c:
            c.execute("SELECT id FROM buyers WHERE id='demo-hotel' FOR UPDATE")
            rules = c.execute(
                "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
            ).fetchone()["rules"]
            rules["destinations"].append("new-destination")
            c.execute(
                "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)",
                (js(rules),),
            )
            c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    else:
        request_data["destination"] = "hotel-helsinki"
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", 900)
    current = service.get_proposal(agent, first["proposal_id"])
    assert current["approval_status"] == ("expired" if change == "expiry" else "policy_changed")
    assert current["next_action"]["type"] == "request_fresh_proposal"
    request_data["idempotency_key"] = str(uuid4())
    fresh = service.prepare_order(agent, PrepareRequest(**request_data))
    assert fresh["proposal_id"] != first["proposal_id"]
    assert fresh["policy_outcome"] == "ready_to_commit"


def test_approver_amount_and_exception_scope(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)
    with connection() as c:
        c.execute(
            "UPDATE identities SET authority=%s WHERE id='buyer'",
            (js({"currency": "EUR", "max_gross": "1600", "exceptions": ["spend"]}),),
        )
    expect_code("APPROVAL_SCOPE", lambda: decide(buyer, p))
    assert workflow.approval_detail(buyer, p["approval_id"])["can_decide"] is False
    fresh = service.prepare_order(
        agent, mission.model_copy(update={"idempotency_key": str(uuid4())})
    )
    assert fresh["policy_outcome"] == "needs_resolution"
    assert "NO_ELIGIBLE_APPROVER" in [r["code"] for r in fresh["reasons"]]


def test_concurrent_same_key_one_order(service, agent, request_data):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    req = commit(p)
    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(lambda _: service.commit_order(agent, req), range(8)))
    assert len({r["order_id"] for r in receipts}) == 1
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM orders").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) n FROM idempotency").fetchone()["n"] == 1


def test_concurrent_different_keys_and_conflicting_payloads(service, agent, request_data):
    p = service.prepare_order(agent, PrepareRequest(**request_data))

    def submit(_):
        try:
            return service.commit_order(agent, commit(p))["status"]
        except Problem as e:
            return e.code

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(submit, range(4)))
    assert results.count("accepted_mock") == 1 and results.count("ALREADY_COMMITTED") == 3
    p2 = service.prepare_order(
        agent, PrepareRequest(**(request_data | {"idempotency_key": str(uuid4())}))
    )
    req = commit(p2, "same-key-for-different-purchases")
    service.commit_order(agent, req)
    p3 = service.prepare_order(
        agent, PrepareRequest(**(request_data | {"idempotency_key": str(uuid4())}))
    )
    expect_code(
        "IDEMPOTENCY_CONFLICT", lambda: service.commit_order(agent, commit(p3, req.idempotency_key))
    )


def test_competing_decisions_and_commit(service, agent, buyer, mission):
    p = service.prepare_order(agent, mission)

    def run(action):
        try:
            if action == "commit":
                return service.commit_order(agent, commit(p))["status"]
            return decide(buyer, p, action)["approval_status"]
        except Problem as e:
            return e.code

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(run, ["approve", "reject", "commit"]))
    final = service.get_proposal(agent, p["proposal_id"])
    assert final["approval_status"] in ("approved", "rejected")
    assert not ("approved" in results and "rejected" in results)
    if final["order_id"]:
        assert final["approval_status"] == "approved"


def test_deposit_totals_and_overbuy(service, agent, buyer, request_data):
    request_data.update(
        requirements={}, lines=[{"product_id": "460123", "amount": "10", "unit": "KI"}]
    )
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert p["snapshot"]["lines"][0]["deposit_lines"][0]["quantity"] == "120"
    assert p["snapshot"]["deposits_gross"] == "15.60"
    assert p["snapshot"]["gross_total"] == "32.60"
    request_data["idempotency_key"] = str(uuid4())
    request_data["lines"] = [{"product_id": "464306", "amount": "10.5", "unit": "L"}]
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    assert Decimal(p["snapshot"]["lines"][0]["quantity"]["sales_quantity"]) == 11
    assert p["policy_outcome"] == "approval_required"
    request_data["idempotency_key"] = str(uuid4())
    request_data["allow_overbuy"] = False
    assert (
        service.prepare_order(agent, PrepareRequest(**request_data))["policy_outcome"] == "denied"
    )


def test_invalid_policy_does_not_default_to_permission(service, agent, request_data):
    with connection() as c:
        rules = c.execute("SELECT rules FROM policies WHERE buyer_id='demo-hotel'").fetchone()[
            "rules"
        ]
        rules["substitution"] = "unexpected-permissive-mode"
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)", (js(rules),)
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    expect_code(
        "INVALID_POLICY_CONFIGURATION",
        lambda: service.prepare_order(agent, PrepareRequest(**request_data)),
    )
