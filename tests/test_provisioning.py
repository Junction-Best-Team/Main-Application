"""JNP3-IDN-002 (Draft, owner decision Q-35): an agent identity is provisioned without any spend
authority. seed() is the only provisioning path today; a later per-buyer provisioning command must
satisfy the same assertions.

The seeded agents carry an empty authority, the policy rules no autonomous limit, and legacy-shaped
databases keep working (nothing is migrated).
"""

from uuid import uuid4

from aimo import auth
from aimo.cli import seed
from aimo.db import connection, js
from aimo.purchases import context
from aimo.schemas import PrepareRequest

FORBIDDEN_FRAGMENTS = ("limit", "max", "spend", "exceptions")


def rows(sql, *args):
    with connection() as c:
        return c.execute(sql, args).fetchall()


def agent_rows():
    return rows("SELECT * FROM identities WHERE role='agent' ORDER BY id")


def tables_snapshot():
    return {
        "buyers": rows("SELECT * FROM buyers ORDER BY id"),
        "policies": rows("SELECT * FROM policies ORDER BY buyer_id, version"),
        "identities": rows("SELECT id,buyer_id,role,active,authority FROM identities ORDER BY id"),
        "internal_agents": rows("SELECT * FROM internal_agents ORDER BY buyer_id"),
    }


def test_seed_creates_the_demo_and_the_internal_agent():
    ids = {r["id"] for r in agent_rows()}
    assert "demo-agent" in ids
    assert len(ids) == 2
    assert any(i.startswith("internal:") for i in ids)


def test_every_seeded_agent_authority_is_empty():
    for row in agent_rows():
        assert row["authority"] == {}, row["id"]


def test_no_seeded_agent_authority_key_names_a_limit_or_spend():
    for row in agent_rows():
        for key in row["authority"]:
            assert not any(f in key.lower() for f in FORBIDDEN_FRAGMENTS), (row["id"], key)


def test_seeded_policy_rules_have_no_autonomous_limit():
    policies = rows("SELECT rules FROM policies")
    assert policies
    for row in policies:
        assert "autonomous_limit" not in row["rules"]


def test_seeded_approver_keeps_its_maximum_but_has_no_spend_exception():
    approver = rows("SELECT authority FROM identities WHERE id='buyer'")[0]["authority"]
    assert approver["max_gross"] == "5000.00"
    assert approver["currency"] == "EUR"
    assert approver["exceptions"] == ["substitution", "overbuy"]


def test_internal_agent_is_mapped_and_cannot_log_in_with_a_bearer():
    mapped = rows(
        "SELECT i.* FROM internal_agents m JOIN identities i ON i.id=m.identity_id "
        "WHERE m.buyer_id='demo-hotel'"
    )
    assert len(mapped) == 1
    assert mapped[0]["role"] == "agent" and mapped[0]["active"]
    assert mapped[0]["credential_hash"].startswith("!")


def test_every_seeded_agent_credential_is_not_a_usable_hash():
    for row in agent_rows():
        assert row["credential_hash"].startswith("!"), row["id"]


def test_internal_agent_resolves_for_the_buyer(buyer):
    internal = auth.internal_agent(buyer)
    assert internal["role"] == "agent"
    assert internal["id"] == rows("SELECT identity_id FROM internal_agents")[0]["identity_id"]


def test_seed_twice_is_idempotent():
    before = tables_snapshot()
    seed()
    assert tables_snapshot() == before


def test_seed_does_not_rewrite_an_existing_agent_row():
    """ON CONFLICT DO NOTHING: deployed rows keep whatever shape they have."""
    custom = {"currency": "EUR", "autonomous_limit": "777"}
    with connection() as c:
        c.execute("UPDATE identities SET authority=%s WHERE id='demo-agent'", (js(custom),))
    seed()
    assert rows("SELECT authority FROM identities WHERE id='demo-agent'")[0]["authority"] == custom


# --- A legacy-shaped database keeps working (tolerance, no data migration) -------


def make_legacy_database():
    legacy_rules = {
        "currency": "EUR",
        "autonomous_limit": "1500.00",
        "destinations": ["hotel-helsinki"],
        "substitution": "requires_approval",
        "overbuy": "requires_approval",
        "whole_sales_units": True,
        "approved_product_ids": ["464306"],
    }
    with connection() as c:
        buyer = c.execute("SELECT * FROM buyers WHERE id='demo-hotel' FOR UPDATE").fetchone()
        version = buyer["current_policy"] + 1
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',%s,%s)",
            (version, js(legacy_rules)),
        )
        c.execute("UPDATE buyers SET current_policy=%s WHERE id='demo-hotel'", (version,))
        c.execute(
            "UPDATE identities SET authority=%s WHERE id='demo-agent'",
            (js({"currency": "EUR", "autonomous_limit": "1500.00"}),),
        )
        c.execute(
            "UPDATE identities SET authority=%s WHERE role='agent' AND id LIKE 'internal:%%'",
            (js({"currency": "EUR", "autonomous_limit": "0"}),),
        )
        c.execute(
            "UPDATE identities SET authority=%s WHERE id='buyer'",
            (
                js(
                    {
                        "currency": "EUR",
                        "max_gross": "5000.00",
                        "exceptions": ["spend", "substitution", "overbuy"],
                    }
                ),
            ),
        )


def test_legacy_shaped_database_passes_context_for_every_role():
    make_legacy_database()
    for row in rows("SELECT * FROM identities WHERE buyer_id='demo-hotel' ORDER BY id"):
        with connection() as c:
            buyer, policy, actor, approvers = context(c, row)
        assert policy["rules"]["autonomous_limit"] == "1500.00"
        assert actor["id"] == row["id"]
        assert [a["id"] for a in approvers] == ["buyer"]


def test_legacy_shaped_database_still_prepares_a_purchase(service, request_data):
    make_legacy_database()
    agent = rows("SELECT * FROM identities WHERE id='demo-agent'")[0]
    request_data["idempotency_key"] = str(uuid4())
    proposal = service.prepare_order(agent, PrepareRequest.model_validate(request_data))
    assert proposal["policy_outcome"] in {"ready_to_commit", "approval_required"}


def test_new_shaped_agent_passes_context(agent):
    assert agent["authority"] == {}
    with connection() as c:
        context(c, agent)
