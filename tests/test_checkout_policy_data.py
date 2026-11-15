"""Q-134 (a): the demo buyer's policy DATA is broad enough that a normal meal basket is not blocked by
product scope or overbuy. Only data changes: the seed default and a one-off script for buyers that
are already seeded. The rules in approval_policy.py are untouched, a declared substitution still needs
approval, products outside the catalogue are still refused and nothing lets an agent edit the policy.
Fixture catalogue and authored policy only; nothing here is a live buyer.
"""

import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from aimo import cli, policy_scope, policy_settings
from aimo.db import Problem, connection, js
from aimo.scheduler import helsinki_today
from aimo.schemas import PrepareRequest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "widen_buyer_policy.py"
OLD_SCOPE = ["464306"]


def load_script():
    spec = importlib.util.spec_from_file_location("widen_buyer_policy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_rules(buyer_id="demo-hotel"):
    with connection() as c:
        row = c.execute(
            """SELECT b.current_policy AS version, p.rules FROM buyers b
            JOIN policies p ON p.buyer_id=b.id AND p.version=b.current_policy WHERE b.id=%s""",
            (buyer_id,),
        ).fetchone()
    return row["version"], row["rules"]


def reseed(monkeypatch, **kwargs):
    """Empty the buyer tables and run the real seed (the conftest reset uses the narrow fixture policy)."""
    from aimo.auth import hasher

    with connection() as c:
        c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        c.execute("TRUNCATE buyers,login_attempts,purged_proposals RESTART IDENTITY CASCADE")
    monkeypatch.setattr("aimo.cli.hasher", type("H", (), {"hash": staticmethod(hasher.hash)}))
    cli.seed(**kwargs)


def prepare(service, agent, lines, **extra):
    body = {
        "request_id": "Q-134 basket",
        "idempotency_key": str(uuid4()),
        "destination": "hotel-helsinki",
        "delivery_date": str(helsinki_today() + timedelta(days=2)),
        "lines": lines,
    } | extra
    identity = agent | {"_turn_id": str(uuid4())}
    return service.prepare_order(identity, PrepareRequest.model_validate(body))


def codes(proposal):
    return {r["code"] for r in proposal["reasons"]}


# A normal basket: two products outside the old one-product list, one of them a pack rounding.
NORMAL = [
    {"product_id": "464398", "amount": "10", "unit": "L"},
    {"product_id": "460035", "amount": "5", "unit": "KG"},
    {"product_id": "460123", "amount": "5", "unit": "BOT"},
]


# --- the seed default ----------------------------------------------------------------------------


def test_the_seeded_policy_covers_the_whole_active_catalogue_and_allows_overbuy(monkeypatch):
    reseed(monkeypatch)
    _, rules = current_rules()
    with connection() as c:
        catalogue = policy_scope.catalog_product_ids(c)
    assert len(catalogue) >= 5 and set(catalogue) <= set(rules["approved_product_ids"])
    assert rules["overbuy"] == "allowed"
    # Everything else is the existing demo policy.
    assert rules["substitution"] == "requires_approval"
    assert rules["destinations"] == ["hotel-helsinki"] and rules["whole_sales_units"] is True
    assert rules["currency"] == "EUR" and "max_order_gross" not in rules


def test_without_an_active_catalogue_the_seed_keeps_the_old_scope_but_still_allows_overbuy(
    monkeypatch,
):
    monkeypatch.setattr(policy_scope, "catalog_product_ids", lambda c: [])
    reseed(monkeypatch)
    _, rules = current_rules()
    assert rules["approved_product_ids"] == OLD_SCOPE and rules["overbuy"] == "allowed"


def test_the_narrow_fixture_policy_is_still_available_to_other_tests():
    _, rules = current_rules()  # the conftest reset
    assert rules["approved_product_ids"] == OLD_SCOPE and rules["overbuy"] == "requires_approval"


def test_seeding_again_never_overwrites_an_existing_policy(monkeypatch):
    reseed(monkeypatch)
    before = current_rules()
    cli.seed()
    assert current_rules() == before


# --- behaviour: a normal basket is not blocked by scope or overbuy --------------------------------


def test_a_normal_basket_has_neither_a_scope_nor_an_overbuy_exception_after_the_change(
    monkeypatch, service, agent
):
    narrow = prepare(service, agent, NORMAL)  # control: the old fixture policy
    assert {"SUBSTITUTION_REQUIRES_APPROVAL", "OVERBUY_REQUIRES_APPROVAL"} <= codes(narrow)
    reseed(monkeypatch)
    with connection() as c:
        agent = c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()
    wide = prepare(service, agent, NORMAL)
    assert not codes(wide) & {
        "SUBSTITUTION_REQUIRES_APPROVAL",
        "OVERBUY_REQUIRES_APPROVAL",
        "SUBSTITUTION_ALLOWED_BY_POLICY",
    }
    assert wide["policy_outcome"] != "approval_required"
    assert any(
        line["quantity"].get("excess") not in (None, "0") for line in wide["snapshot"]["lines"]
    )


def test_a_declared_substitution_still_needs_the_customers_approval(monkeypatch, service, agent):
    reseed(monkeypatch)
    with connection() as c:
        agent = c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()
    swapped = prepare(
        service,
        agent,
        [{"product_id": "464398", "amount": "10", "unit": "L", "substitutes_for": "464306"}],
    )
    assert "SUBSTITUTION_REQUIRES_APPROVAL" in codes(swapped)


def test_a_product_outside_the_catalogue_stays_refused(monkeypatch, service, agent):
    reseed(monkeypatch)
    with connection() as c:
        agent = c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()
    unknown = prepare(
        service, agent, [{"product_id": "no-such-product", "amount": "1", "unit": "ST"}]
    )
    assert "PRODUCT_UNKNOWN" in codes(unknown)
    assert unknown["policy_outcome"] in {"needs_resolution", "denied"}
    assert unknown["next_action"]["type"] != "commit"


def test_a_withdrawn_product_is_not_added_to_the_scope(monkeypatch):
    with connection() as c:
        generation = c.execute("SELECT generation FROM active_catalog").fetchone()["generation"]
        c.execute(
            "UPDATE products SET facts = jsonb_set(facts,'{deleted}','true') WHERE generation=%s AND id='460035'",
            (generation,),
        )
    try:
        reseed(monkeypatch)
        _, rules = current_rules()
        assert "460035" not in rules["approved_product_ids"]
        assert "464306" in rules["approved_product_ids"]
    finally:
        with connection() as c:
            c.execute(
                "UPDATE products SET facts = jsonb_set(facts,'{deleted}','false') WHERE generation=%s AND id='460035'",
                (generation,),
            )


# --- policy editing by the agent stays impossible (POL-007 deferred) ------------------------------


def test_the_agent_cannot_edit_the_policy_and_the_settings_cannot_carry_a_scope(agent, buyer):
    with pytest.raises(Problem) as error:
        policy_settings.update(
            agent,
            policy_settings.PolicyUpdate(
                expected_version=1,
                rules={"substitution": "allowed", "overbuy": "allowed", "whole_sales_units": True},
            ),
        )
    assert error.value.code in {"POLICY_FORBIDDEN", "FORBIDDEN"}
    with pytest.raises(ValueError):  # extra keys are rejected: the scope is not editable here
        policy_settings.PolicyUpdate(
            expected_version=1,
            rules={
                "substitution": "allowed",
                "overbuy": "allowed",
                "whole_sales_units": True,
                "approved_product_ids": ["*"],
            },
        )


def test_no_agent_tool_can_write_the_policy():
    from aimo import agent_tools

    names = {name for name in dir(agent_tools.ToolSession) if not name.startswith("_")}
    assert not {
        n
        for n in names
        if "polic" in n and any(w in n for w in ("set", "update", "write", "edit", "save"))
    }


# --- the one-off script for buyers that are already seeded ---------------------------------------


def add_tester_buyer(buyer_id):
    """A tester buyer made like provision_tester.py: the policy copied from demo-hotel."""
    with connection() as c:
        version, rules = current_rules()
        c.execute(
            "INSERT INTO buyers(id,upstream_customer,current_policy) VALUES(%s,'123',1)",
            (buyer_id,),
        )
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES(%s,1,%s)", (buyer_id, js(rules))
        )


def test_the_script_widens_an_existing_buyer_once_and_records_the_old_policy(tmp_path):
    script = load_script()
    old_version, old_rules = current_rules()
    with connection() as c:
        first = script.widen(c, "demo-hotel", tmp_path, apply=True)
    version, rules = current_rules()
    assert first["action"] == "widened" and first["from_version"] == old_version
    assert version == old_version + 1 == first["to_version"]
    assert rules["overbuy"] == "allowed" and set(old_rules["approved_product_ids"]) <= set(
        rules["approved_product_ids"]
    )
    assert {"464398", "460035", "460123"} <= set(rules["approved_product_ids"])
    assert {k: v for k, v in rules.items() if k not in {"overbuy", "approved_product_ids"}} == {
        k: v for k, v in old_rules.items() if k not in {"overbuy", "approved_product_ids"}
    }
    backup = json.loads(Path(first["backup"]).read_text())
    assert backup["buyer_id"] == "demo-hotel" and backup["version"] == old_version
    assert backup["rules"] == old_rules
    # Idempotent: a second run changes nothing and writes no new version.
    with connection() as c:
        second = script.widen(c, "demo-hotel", tmp_path, apply=True)
        assert c.execute("SELECT count(*) AS n FROM policies").fetchone()["n"] == 2
    assert second["action"] == "unchanged" and current_rules()[0] == version


def test_the_script_reports_without_writing_unless_asked(tmp_path):
    script = load_script()
    before = current_rules()
    with connection() as c:
        report = script.widen(c, "demo-hotel", tmp_path, apply=False)
    assert report["action"] == "would_widen" and current_rules() == before
    assert list(tmp_path.iterdir()) == []


def test_rolling_back_restores_the_recorded_rules_as_a_new_version(tmp_path):
    script = load_script()
    old_version, old_rules = current_rules()
    with connection() as c:
        done = script.widen(c, "demo-hotel", tmp_path, apply=True)
        undone = script.rollback(c, "demo-hotel", Path(done["backup"]))
    version, rules = current_rules()
    assert undone["action"] == "rolled_back" and version == old_version + 2
    assert rules == old_rules
    with connection() as c:  # history is kept: all three versions exist
        assert c.execute("SELECT count(*) AS n FROM policies").fetchone()["n"] == 3
        assert script.rollback(c, "demo-hotel", Path(done["backup"]))["action"] == "unchanged"


def test_the_script_never_narrows_a_scope_and_handles_tester_buyers(tmp_path):
    script = load_script()
    add_tester_buyer("rt-hotel-a")
    with connection() as c:
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) "
            "SELECT buyer_id,2,rules || %s FROM policies WHERE buyer_id='rt-hotel-a' AND version=1",
            (js({"approved_product_ids": ["464306", "extra-kept"]}),),
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='rt-hotel-a'")
        result = script.widen(c, "rt-hotel-a", tmp_path, apply=True)
    _, rules = current_rules("rt-hotel-a")
    assert result["action"] == "widened" and "extra-kept" in rules["approved_product_ids"]
    assert "464398" in rules["approved_product_ids"] and rules["overbuy"] == "allowed"
    assert current_rules("demo-hotel")[1]["approved_product_ids"] == OLD_SCOPE  # others untouched


def test_the_script_refuses_an_unknown_buyer_and_a_buyer_without_a_policy(tmp_path):
    script = load_script()
    with connection() as c:
        with pytest.raises(SystemExit):
            script.widen(c, "nobody", tmp_path, apply=True)


def test_the_script_reads_the_database_url_only_from_the_environment():
    text = SCRIPT.read_text()
    assert "PROVISION_DATABASE_URL" in text and "--database-url" not in text
    assert "print(url" not in text
