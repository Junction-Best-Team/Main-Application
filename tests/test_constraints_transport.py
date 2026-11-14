"""POL-008 transport: the server-only constraint record from ToolSession to the stored revision.

The model can never write the record (extra tool arguments are forbidden); the service stores it
inside the proposal revision's request JSON, so the fingerprint covers it and refresh and commit
re-read it from there. Fixture mode only, real PostgreSQL, real policy function.
"""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aimo import approval_workflow as workflow
from aimo.agent_tools import ToolSession
from aimo.db import Problem, connection
from aimo.schemas import CommitRequest, PrepareRequest, ProposalResponse


def stated(name, value, source="user_request", confirmed=True):
    return {"name": name, "value": value, "source": source, "confirmed": confirmed}


def prepare(service, agent, request_data, constraints=None, **changes):
    request_data.update(idempotency_key=str(uuid4()), requirements={}, **changes)
    return service.prepare_order(agent, PrepareRequest(**request_data), constraints=constraints)


def stored(proposal_id, revision=1):
    with connection() as c:
        return c.execute(
            "SELECT * FROM proposal_revisions WHERE proposal_id=%s AND revision=%s",
            (proposal_id, revision),
        ).fetchone()


def codes(proposal):
    return {r["code"] for r in proposal["reasons"]}


def commit(p):
    return CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )


def tamper(proposal_id, constraints):
    """Simulate a changed stored record. The history table refuses updates, so the guard is
    lifted for this one statement, in the test only, and restored in a separate transaction."""
    row = stored(proposal_id)
    with connection() as c:
        c.execute("ALTER TABLE proposal_revisions DISABLE TRIGGER USER")
    try:
        with connection() as c:
            c.execute(
                "UPDATE proposal_revisions SET request=%s WHERE proposal_id=%s AND revision=1",
                (json.dumps(row["request"] | {"constraints": constraints}), proposal_id),
            )
    finally:
        with connection() as c:
            c.execute("ALTER TABLE proposal_revisions ENABLE TRIGGER USER")


def total_of(service, agent, request_data):
    return prepare(service, agent, request_data)["snapshot"]["gross_total"]


# --- stored shape ---------------------------------------------------------------------------


def test_without_constraints_the_stored_request_has_no_constraints_key(
    service, agent, request_data
):
    p = prepare(service, agent, request_data)
    assert "constraints" not in stored(p["proposal_id"])["request"]
    assert "constraints" not in p["request"]


def test_constraints_are_stored_in_the_revision_request_and_not_returned_to_callers(
    service, agent, request_data
):
    record = [stated("budget_gross", "500.00"), stated("milk_free", True)]
    p = prepare(service, agent, request_data, record)
    assert stored(p["proposal_id"])["request"]["constraints"] == record
    assert "constraints" not in p["request"]
    ProposalResponse.model_validate(p)  # the browser-facing shape is unchanged
    again = service.get_proposal(agent, p["proposal_id"])
    assert "constraints" not in again["request"]
    ProposalResponse.model_validate(again)


def test_a_malformed_record_is_refused_before_anything_is_stored(service, agent, request_data):
    bad = [stated("budget_gross", "not a number"), stated("colour", "red")]
    for entry in bad:
        with pytest.raises(ValidationError):
            prepare(service, agent, request_data, [entry])
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0


# --- the record changes the outcome -------------------------------------------------------


def test_a_looser_request_budget_is_enforced_at_the_stored_customer_budget(
    service, agent, request_data
):
    total = float(total_of(service, agent, request_data))
    tight = stated("budget_gross", f"{total - 0.01:.2f}")
    p = prepare(service, agent, request_data, [tight], budget_gross="9999.00")
    assert p["policy_outcome"] == "denied"
    assert {"HARD_BUDGET_EXCEEDED", "CONSTRAINT_LOOSENED"} <= codes(p)
    with pytest.raises(Problem) as error:
        service.commit_order(agent, commit(p))
    assert error.value.code == "COMMIT_BLOCKED"


def test_an_unconfirmed_assumption_in_the_record_changes_nothing(service, agent, request_data):
    assumed = stated("budget_gross", "0.01", "stated_assumption", False)
    p = prepare(service, agent, request_data, [assumed])
    assert p["policy_outcome"] == "ready_to_commit"
    assert codes(p) & {"CONSTRAINT_LOOSENED", "HARD_BUDGET_EXCEEDED"} == set()


def test_a_dropped_dietary_flag_blocks_the_basket(service, agent, request_data):
    p = prepare(service, agent, request_data, [stated("milk_free", True)])
    assert p["policy_outcome"] == "needs_resolution" and "CONSTRAINT_LOOSENED" in codes(p)


# --- revisions and fingerprints -------------------------------------------------------------


def test_the_record_is_part_of_the_material_fingerprint(service, agent, request_data):
    a = prepare(service, agent, request_data, [stated("budget_gross", "500.00")])
    b = prepare(service, agent, request_data, [stated("budget_gross", "400.00")])
    plain = prepare(service, agent, request_data)
    fingerprints = {stored(x["proposal_id"])["fingerprint"] for x in (a, b, plain)}
    assert len(fingerprints) == 3


def test_a_changed_record_with_the_same_key_is_an_idempotency_conflict(
    service, agent, request_data
):
    request_data.update(idempotency_key=str(uuid4()), requirements={})
    request = PrepareRequest(**request_data)
    service.prepare_order(agent, request, constraints=[stated("budget_gross", "500.00")])
    service.prepare_order(agent, request, constraints=[stated("budget_gross", "500.00")])  # retry
    with pytest.raises(Problem) as error:
        service.prepare_order(agent, request, constraints=[stated("budget_gross", "400.00")])
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_changing_the_stored_record_makes_commit_open_a_new_revision(
    service, agent, request_data, confirm_terms
):
    p = prepare(service, agent, request_data, [stated("budget_gross", "9999.00")])
    assert p["policy_outcome"] == "ready_to_commit"
    confirm_terms(p)
    total = p["snapshot"]["gross_total"]
    tight = [stated("budget_gross", f"{float(total) - 0.01:.2f}")]
    tamper(p["proposal_id"], tight)
    # The rendered proposal re-reads the stored record too.
    assert service.get_proposal(agent, p["proposal_id"])["approval_status"] == "authority_changed"
    revised = service.commit_order(agent, commit(p))
    assert revised["status"] == "revised" and revised["revision"] == 2
    assert revised["policy_outcome"] == "denied" and "HARD_BUDGET_EXCEEDED" in codes(revised)
    assert stored(p["proposal_id"], 2)["request"]["constraints"] == tight  # carried forward
    assert stored(p["proposal_id"], 2)["fingerprint"] != stored(p["proposal_id"])["fingerprint"]


def test_commit_of_an_untouched_record_does_not_open_a_revision(
    service, agent, request_data, confirm_terms
):
    p = prepare(service, agent, request_data, [stated("budget_gross", "9999.00")])
    confirm_terms(p)
    assert service.commit_order(agent, commit(p))["status"] == "accepted_mock"


# --- the model can never set the record -------------------------------------------------


def tool_session(agent, service, **kwargs):
    return ToolSession(dict(agent) | {"_turn_id": str(uuid4())}, service, **kwargs)


PLAN = {
    "title": "Milk dishes",
    "portions": 10,
    "ingredients": [
        {"name": "sauce", "amount": "10", "unit": "L", "product_id": "464306"},
    ],
}


def basket(delivery_date, **extra):
    return {
        "request_id": "milk-dishes",
        "destination": "hotel-helsinki",
        "delivery_date": delivery_date,
        "lines": [{"product_id": "464306", "amount": "10", "unit": "L"}],
    } | extra


def ready_session(agent, service, **kwargs):
    session = tool_session(agent, service, **kwargs)
    session.invoke("get_product", json.dumps({"product_id": "464306"}))
    session.invoke("publish_meal_plan", json.dumps(PLAN))
    return session


def test_a_model_supplied_constraints_argument_is_rejected(agent, service, request_data):
    when = request_data["delivery_date"]
    session = ready_session(agent, service)
    forged = [stated("budget_gross", "9999.00")]
    for extra in ({"constraints": forged}, {"constraints": []}):
        with pytest.raises(Problem) as error:
            session.invoke("prepare_order", json.dumps(basket(when, **extra)))
        assert error.value.code == "INVALID_TOOL_ARGUMENTS" and error.value.status == 422
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0


def test_the_model_facing_schemas_do_not_mention_constraints(agent, service):
    from aimo.agent_tools import PrepareOrderInput
    from aimo.schemas import PurchaseRequest

    assert "constraints" not in PrepareOrderInput.model_fields
    assert "constraints" not in PrepareOrderInput.model_json_schema()["properties"]
    assert "constraints" not in PurchaseRequest.model_fields
    assert "constraints" not in PrepareRequest.model_fields
    specs = tool_session(agent, service).registry
    assert "constraints" not in json.dumps(
        [spec.request.model_json_schema() for spec in specs.values()]
    )


def test_a_server_supplied_record_reaches_the_stored_revision(agent, service, request_data):
    record = [stated("budget_gross", "9999.00"), stated("milk_free", True)]
    session = ready_session(agent, service, constraints=record)
    proposal = session.invoke(
        "prepare_order", json.dumps(basket(request_data["delivery_date"], requirements={}))
    )
    assert stored(proposal["proposal_id"])["request"]["constraints"] == record
    assert "constraints" not in proposal["request"]
    assert "CONSTRAINT_LOOSENED" in codes(proposal)  # the model's request dropped milk_free


def test_a_session_without_a_record_stores_none(agent, service, request_data):
    session = ready_session(agent, service)
    proposal = session.invoke("prepare_order", json.dumps(basket(request_data["delivery_date"])))
    assert "constraints" not in stored(proposal["proposal_id"])["request"]


def test_run_turn_passes_the_record_to_the_tool_session(monkeypatch, agent, service):
    from aimo import agent as runner

    seen = {}

    class Stop(Exception):
        pass

    def spy(identity, service_, guard=None, constraints=None):
        seen["constraints"] = constraints
        raise Stop

    monkeypatch.setattr(runner, "ToolSession", spy)
    identity = dict(agent) | {"_turn_id": str(uuid4())}
    record = [stated("milk_free", True)]
    with pytest.raises(Stop):
        runner.run_turn(identity, [{"role": "user", "content": "hi"}], service, constraints=record)
    assert seen["constraints"] == record
    with pytest.raises(Stop):
        runner.run_turn(identity, [{"role": "user", "content": "hi"}], service)
    assert seen["constraints"] is None


def test_workflow_prepare_order_takes_the_record_as_a_server_argument_defaulting_to_none():
    import inspect

    parameter = inspect.signature(workflow.prepare_order).parameters["constraints"]
    assert parameter.default is None
