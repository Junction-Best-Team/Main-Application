"""POL-008 producer (owner Q-97): the customer's structured fields become trusted constraints.

Constraints come only from what the signed-in customer sets on the message-send request: a hard
budget and the lactose-free and milk-free toggles (source `user_request`, confirmed). The model
never sets them. The record is stored with the turn (migration 021, never in a UI-visible field),
covered by the idempotency hash, carried forward across the conversation (the latest value per
name wins) and handed to the runner as `constraints=`, which reaches `prepare_order` through
`ToolSession` (PR #133). Fixture mode, real PostgreSQL.
"""

import json
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aimo.api import create_app
from aimo.chat_schemas import AgentTurn, MessageConstraints, MessageRequest
from aimo.db import connection
from aimo.schemas import PrepareRequest
from aimo.worker import run_once


def signed(client):
    result = client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert result.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": result.json()["csrf_token"]}


@pytest.fixture
def chat(service):
    with TestClient(create_app(service)) as client:
        headers = signed(client)
        cid = client.post(
            "/api/conversations", headers=headers, json={"idempotency_key": str(uuid4())}
        ).json()["id"]

        def send(text="Order milk for the hotel.", key=None, **fields):
            body = {"text": text, "idempotency_key": key or str(uuid4())}
            if fields:
                body["constraints"] = fields
            return client.post(f"/api/conversations/{cid}/messages", headers=headers, json=body)

        yield client, headers, cid, send


def stored(cid):
    with connection() as c:
        return c.execute(
            "SELECT * FROM conversation_turns WHERE conversation_id=%s ORDER BY created_at",
            (cid,),
        ).fetchall()


def record(name, value):
    return {"name": name, "value": value, "source": "user_request", "confirmed": True}


class Capture:
    """A runner that records what the worker hands over, like `agent.run_turn`."""

    def __init__(self):
        self.calls = []

    def __call__(self, actor, history, shared, **extra):
        self.calls.append(extra)
        return AgentTurn(text="Noted.")


# --- the request model -------------------------------------------------------------------------


def test_the_fields_are_optional_and_validated():
    assert MessageRequest(text="hi", idempotency_key="k" * 8).constraints is None
    fields = MessageConstraints(budget_gross="250.5", lactose_free=True)
    assert fields.budget_gross == Decimal("250.5") and fields.milk_free is None
    for bad in ({"budget_gross": "0"}, {"budget_gross": "-5"}, {"budget_gross": "abc"}, {"vegan": True}):
        with pytest.raises(ValidationError):
            MessageConstraints(**bad)
    with pytest.raises(ValidationError):
        MessageConstraints()  # an empty record says nothing; omit the field instead


# --- storing it ---------------------------------------------------------------------------------


def test_the_record_is_stored_with_the_turn_and_is_not_part_of_a_finished_conversation(
    chat, service
):
    client, headers, cid, send = chat
    response = send(budget_gross="250.50", lactose_free=True)
    assert response.status_code == 200, response.text
    (turn,) = stored(cid)
    assert sorted(turn["constraints"], key=lambda c: c["name"]) == [
        record("budget_gross", "250.50"),
        record("lactose_free", True),
    ]
    # while the message is unfinished, the client's own retry carries the same fields back
    retry = response.json()["retry_message"]
    assert retry["constraints"] == {"budget_gross": "250.50", "lactose_free": True, "milk_free": None}
    run_once(service, Capture())
    done = client.get(f"/api/conversations/{cid}", headers=headers)
    assert done.json()["retry_message"] is None
    assert "constraints" not in done.text and "250.50" not in done.text


def test_retrying_a_failed_message_with_the_returned_fields_is_the_same_message(chat, service):
    client, headers, cid, send = chat
    key = str(uuid4())
    first = send(key=key, budget_gross="100", milk_free=True)
    retry = first.json()["retry_message"]
    assert send(key=retry["idempotency_key"], **retry["constraints"]).status_code == 200
    assert len(stored(cid)) == 1


def test_a_message_without_the_field_stores_nothing(chat):
    _, _, cid, send = chat
    assert send().status_code == 200
    assert stored(cid)[0]["constraints"] is None


def test_the_same_key_with_another_record_is_an_idempotency_conflict(chat):
    _, _, cid, send = chat
    key = str(uuid4())
    assert send(key=key, budget_gross="100").status_code == 200
    assert send(key=key, budget_gross="100").status_code == 200  # an exact retry is fine
    for changed in ({"budget_gross": "500"}, {"budget_gross": "100", "milk_free": True}, {}):
        response = send(key=key, **changed)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(stored(cid)) == 1


def test_the_idempotency_hash_of_a_message_without_the_field_is_unchanged(chat):
    from aimo.db import fingerprint

    _, _, cid, send = chat
    key = str(uuid4())
    text = "Order milk for the hotel."
    send(text=text, key=key)
    assert stored(cid)[0]["payload_hash"] == fingerprint({"text": text})


# --- handing it to the runner -------------------------------------------------------------------


def test_the_worker_hands_the_record_to_the_runner(chat, service):
    _, _, cid, send = chat
    send(budget_gross="250.50", milk_free=True)
    capture = Capture()
    assert run_once(service, capture)
    (extra,) = capture.calls
    assert sorted(extra["constraints"], key=lambda c: c["name"]) == [
        record("budget_gross", "250.50"),
        record("milk_free", True),
    ]


def test_without_a_record_the_runner_gets_no_constraints_argument(chat, service):
    _, _, cid, send = chat
    send()
    capture = Capture()
    run_once(service, capture)
    assert capture.calls == [{}]


def test_an_earlier_record_stays_in_force_and_the_latest_value_per_name_wins(chat, service):
    _, _, cid, send = chat
    capture = Capture()
    send(budget_gross="100", lactose_free=True)
    run_once(service, capture)
    send(text="Add some butter.")  # no field: the budget and the diet still apply
    run_once(service, capture)
    send(text="Raise it.", budget_gross="400", lactose_free=False)
    run_once(service, capture)
    by_name = [{c["name"]: c["value"] for c in call.get("constraints", [])} for call in capture.calls]
    assert by_name == [
        {"budget_gross": "100", "lactose_free": True},
        {"budget_gross": "100", "lactose_free": True},
        {"budget_gross": "400"},  # lactose_free=false withdrew that requirement
    ]


def test_a_colleagues_record_in_another_conversation_is_not_carried_over(chat, service):
    client, headers, cid, send = chat
    send(budget_gross="100")
    run_once(service, Capture())
    other = client.post(
        "/api/conversations", headers=headers, json={"idempotency_key": str(uuid4())}
    ).json()["id"]
    client.post(
        f"/api/conversations/{other}/messages",
        headers=headers,
        json={"text": "A different purchase.", "idempotency_key": str(uuid4())},
    )
    capture = Capture()
    run_once(service, capture)
    assert capture.calls == [{}]


# --- the effect on a basket ---------------------------------------------------------------------


def test_a_looser_budget_from_the_model_is_stopped_at_the_customers_number(chat, service, request_data):
    """The runner stands in for the model: it asks for a larger budget than the customer set."""
    _, _, cid, send = chat
    send(budget_gross="10")
    outcomes = []

    def runner(actor, history, shared, constraints=None):
        request_data["budget_gross"] = "5000"
        p = shared.prepare_order(
            actor, PrepareRequest.model_validate(request_data), constraints=constraints
        )
        outcomes.append((p["policy_outcome"], {r["code"] for r in p["reasons"]}))
        return AgentTurn(text="Prepared.", proposal_id=p["proposal_id"])

    run_once(service, runner)
    outcome, codes = outcomes[0]
    assert outcome == "denied" and {"CONSTRAINT_LOOSENED", "HARD_BUDGET_EXCEEDED"} <= codes


def test_a_dropped_diet_flag_needs_resolution(chat, service, request_data):
    _, _, cid, send = chat
    send(lactose_free=True)
    outcomes = []

    def runner(actor, history, shared, constraints=None):
        request_data["requirements"] = {}
        p = shared.prepare_order(
            actor, PrepareRequest.model_validate(request_data), constraints=constraints
        )
        outcomes.append((p["policy_outcome"], {r["code"] for r in p["reasons"]}))
        return AgentTurn(text="Prepared.", proposal_id=p["proposal_id"])

    run_once(service, runner)
    assert outcomes[0][0] == "needs_resolution" and "CONSTRAINT_LOOSENED" in outcomes[0][1]


def test_the_model_cannot_set_the_record_through_a_tool_argument():
    from aimo.agent_tools import ToolSession

    session = ToolSession({"id": "i", "buyer_id": "b", "role": "agent", "_turn_id": "t"}, object())
    schema = json.dumps([d["function"]["parameters"] for d in session.definitions])
    assert "constraints" not in schema


# --- migration 021 ------------------------------------------------------------------------------


def test_migration_021_adds_one_nullable_column_and_nothing_else():
    from pathlib import Path

    text = Path("migrations/021_turn_constraints.sql").read_text()
    statements = [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("--")
    ]
    assert statements == ["ALTER TABLE conversation_turns ADD COLUMN constraints jsonb;"]
    with connection() as c:
        column = c.execute(
            """SELECT data_type, is_nullable, column_default FROM information_schema.columns
            WHERE table_name='conversation_turns' AND column_name='constraints'"""
        ).fetchone()
    assert (column["data_type"], column["is_nullable"], column["column_default"]) == (
        "jsonb",
        "YES",
        None,
    )


def test_migration_021_is_in_the_readiness_manifest_and_the_allocation_table():
    from pathlib import Path

    from aimo.schema_state import MANIFEST

    assert MANIFEST["021_turn_constraints.sql"] == [("column", "conversation_turns", "constraints")]
    assert "021_turn_constraints" in Path("migrations/README.md").read_text()
