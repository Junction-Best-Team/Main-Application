"""JNP3-IDN-004: historical actor IDs stay resolvable after credentials are removed or revoked."""

from uuid import uuid4

import psycopg
import pytest

from aimo import approval_workflow as workflow
from aimo.cli import migrate, seed
from aimo.db import connection
from aimo.schemas import CommitRequest, DecisionRequest


def actor_ids():
    with connection() as c:
        ids = {r["actor_id"] for r in c.execute("SELECT actor_id FROM audit_events").fetchall()}
        ids |= {r["agent_id"] for r in c.execute("SELECT agent_id FROM proposals").fetchall()}
        ids |= {
            r["actor_id"]
            for r in c.execute("SELECT actor_id FROM approvals WHERE actor_id IS NOT NULL").fetchall()
        }
    return ids


def test_actor_ids_survive_revocation_reseed_and_migration(
    service, agent, buyer, mission, confirm_terms
):
    p = service.prepare_order(agent, mission)
    workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=1, decision="approve")
    )
    confirm_terms(p)
    receipt = service.commit_order(
        agent,
        CommitRequest(
            proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4())
        ),
    )
    assert receipt["status"] == "accepted_mock"
    recorded = actor_ids()
    assert {"demo-agent", "buyer"} <= recorded

    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id='demo-agent'")
    migrate()  # reruns skip applied files; must not remove or rewrite identities
    seed()

    with connection() as c:
        rows = {
            r["id"]: r
            for r in c.execute("SELECT * FROM identities WHERE id=ANY(%s)", (list(recorded),))
        }
    assert recorded <= set(rows), "every recorded actor must still resolve to an identity row"
    assert rows["demo-agent"]["active"] is False  # revoked, not erased or reactivated
    assert rows["demo-agent"]["credential_hash"].startswith("!")  # placeholder, not a credential
    proposal = workflow.get_proposal(buyer, p["proposal_id"])
    assert proposal["agent_id"] == "demo-agent"
    assert {h["actor_id"] for h in proposal["history"]} <= set(rows)


@pytest.mark.parametrize("identity_id", ["demo-agent", "buyer"])
def test_referenced_identity_cannot_be_deleted(service, agent, buyer, mission, identity_id):
    p = service.prepare_order(agent, mission)
    workflow.record_human_decision(
        buyer, p["approval_id"], DecisionRequest(revision=1, decision="approve")
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection() as c:
            c.execute("DELETE FROM identities WHERE id=%s", (identity_id,))
    with connection() as c:
        assert c.execute("SELECT 1 FROM identities WHERE id=%s", (identity_id,)).fetchone()


def test_internal_agent_identities_are_retained_with_no_login_credential(buyer):
    with connection() as c:
        rows = c.execute(
            """SELECT i.* FROM internal_agents a JOIN identities i ON i.id=a.identity_id
            WHERE a.buyer_id='demo-hotel'"""
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["role"] == "agent" and rows[0]["credential_hash"] == "!internal-no-bearer-login"
