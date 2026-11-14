import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from aimo import policy_settings
from aimo.api import create_app
from aimo.config import settings
from aimo.db import Problem, connection, js
from aimo.permissions import configure_runtime_role
from aimo.schemas import PrepareRequest


def login(client):
    r = client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert r.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": r.json()["csrf_token"]}


def change(buyer, **rules):
    current = policy_settings.get(buyer)
    return policy_settings.PolicyUpdate(
        expected_version=current["policy_version"],
        rules={
            key: value
            for key, value in current["rules"].model_dump().items()
            if key in policy_settings.EditablePolicy.model_fields
        }
        | rules,
    )


def test_browser_save_history_stale_conflict_and_noop(service, buyer):
    with TestClient(create_app(service)) as client:
        url = "/api/settings/policy"
        assert client.get(url).status_code == 401
        headers = login(client)
        original = client.get(url).json()
        assert original["can_edit"] is True
        body = change(buyer, max_order_gross="250.00").model_dump(mode="json")
        assert client.put(url, json=body).status_code == 403
        assert (
            client.put(
                url, json=body, headers=headers | {"Origin": "https://evil.invalid"}
            ).status_code
            == 403
        )
        response = client.put(url, json=body, headers=headers)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["policy_version"] == 2
        assert saved["rules"]["max_order_gross"] == "250.00"
        assert saved["rules"]["approved_product_ids"] == original["rules"]["approved_product_ids"]
        assert saved["rules"]["destinations"] == original["rules"]["destinations"]
        assert saved["history"][0]["actor_id"] == "buyer"
        assert (
            saved["approval_authority"]["max_gross"] == original["approval_authority"]["max_gross"]
        )
        assert client.put(url, json=body, headers=headers).status_code == 409
        body["expected_version"] = 2
        assert client.put(url, json=body, headers=headers).json()["policy_version"] == 2
        with connection() as c:
            assert c.execute("SELECT count(*) AS n FROM policy_changes").fetchone()["n"] == 1
            assert c.execute("SELECT rules FROM policies WHERE version=1").fetchone()["rules"][
                "approved_product_ids"
            ] == ["464306"]


def test_agent_and_revoked_buyer_denied_but_nonmanager_can_edit_with_account_isolation(
    service, buyer, agent
):
    body = change(buyer, substitution="allowed")
    with pytest.raises(Problem) as error:
        policy_settings.update(agent, body)
    assert error.value.status == 403
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other','999',1)")
        c.execute(
            "INSERT INTO policies SELECT 'other',version,rules,created_at FROM policies WHERE buyer_id='demo-hotel'"
        )
    with TestClient(create_app(service)) as client:
        headers = login(client)
        # The account is derived from the session, never from a submitted buyer ID.
        assert (
            client.put(
                "/api/settings/policy",
                json=body.model_dump() | {"buyer_id": "other"},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.put("/api/settings/policy", json=body.model_dump(), headers=headers).status_code
            == 200
        )
        with connection() as c:
            assert (
                c.execute("SELECT current_policy FROM buyers WHERE id='other'").fetchone()[
                    "current_policy"
                ]
                == 1
            )
            c.execute("DELETE FROM policy_managers WHERE identity_id='buyer'")
        assert client.get("/api/settings/policy").json()["can_edit"] is True
        body = change(buyer, overbuy="allowed")
        saved = client.put(
            "/api/settings/policy", json=body.model_dump(mode="json"), headers=headers
        )
        assert saved.status_code == 200
        assert saved.json()["policy_version"] == 3
        assert saved.json()["rules"]["overbuy"] == "allowed"
        with connection() as c:
            c.execute("UPDATE identities SET active=false WHERE id='buyer'")
        assert (
            client.put("/api/settings/policy", json=body.model_dump(), headers=headers).status_code
            == 401
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"approved_product_ids": ["does-not-exist"]},
        {"approved_product_ids": ["*"]},
        {"destinations": [" "]},
        {"destinations": []},
        {"substitution": "sometimes"},
        {"approved_product_ids": None},
        {"max_gross": "999999"},
        {"max_order_gross": "-1"},
        {"max_order_gross": "NaN"},
        {"max_order_gross": "Infinity"},
        {"max_order_gross": "12.345"},
        {"max_order_gross": "1000000000000"},
    ],
)
def test_invalid_configuration_does_not_change_policy(service, buyer, changes):
    body = change(buyer).model_dump()
    body["rules"].update(changes)
    with TestClient(create_app(service)) as client:
        headers = login(client)
        response = client.put("/api/settings/policy", json=body, headers=headers)
        assert response.status_code == 422, response.text
    assert policy_settings.get(buyer)["policy_version"] == 1


def test_policy_change_invalidates_old_confirmation(
    service, buyer, agent, request_data, confirm_terms
):
    p = service.prepare_order(agent, PrepareRequest(**request_data))
    confirm_terms(p)
    policy_settings.update(buyer, change(buyer, overbuy="forbidden"))
    refreshed = service.get_proposal(agent, p["proposal_id"])
    assert refreshed["approval_status"] == "policy_changed"
    assert refreshed["next_action"]["type"] != "commit"
    # Commit creates a fresh revision even when prices and basket are unchanged.
    from aimo.schemas import CommitRequest

    request = CommitRequest(
        proposal_id=p["proposal_id"], revision=p["revision"], idempotency_key=str(uuid4())
    )
    revised = service.commit_order(agent, request)
    assert revised["status"] == "revised" and revised["revision"] == 2
    request.revision = 2
    with pytest.raises(Problem) as error:
        service.commit_order(agent, request)
    assert error.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"


def test_simultaneous_edits_cannot_overwrite_each_other(buyer):
    requests = [change(buyer, overbuy=rule) for rule in ("allowed", "forbidden")]

    def save(request):
        try:
            return policy_settings.update(buyer, request)["policy_version"]
        except Problem as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, requests))
    assert sorted(str(r) for r in results) == ["2", "POLICY_CONFLICT"]


def test_restricted_runtime_uses_narrow_save_without_provisioning(buyer):
    role_name = "policy_settings_test_" + uuid4().hex
    with psycopg.connect(settings().database_url) as c:
        if not c.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]:
            pytest.skip("Requires CREATEROLE in the isolated test database")
        try:
            c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role_name)))
            configure_runtime_role(c, role_name)
            c.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name)))
            for statement in (
                "UPDATE buyers SET current_policy=99",
                "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',99,'{}')",
                "INSERT INTO policy_managers VALUES('demo-hotel','demo-agent')",
                "INSERT INTO policy_changes VALUES('demo-hotel',1,'buyer',now())",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with c.transaction():
                        c.execute(statement)
            rules = change(buyer, overbuy="forbidden").rules.model_dump(mode="json")
            with pytest.raises(psycopg.errors.RaiseException, match="POLICY_FORBIDDEN"):
                with c.transaction():
                    c.execute("SELECT save_buyer_settings('demo-agent',1,%s)", (js(rules),))
            # No separate manager grant is needed; SQL still restricts the editable keys.
            c.execute("RESET ROLE")
            c.execute("DELETE FROM policy_managers WHERE identity_id='buyer'")
            c.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role_name)))
            with pytest.raises(psycopg.errors.RaiseException, match="POLICY_SETTINGS_INVALID"):
                with c.transaction():
                    c.execute(
                        "SELECT save_buyer_settings('buyer',1,%s)",
                        (js(rules | {"destinations": ["elsewhere"]}),),
                    )
            assert (
                c.execute("SELECT save_buyer_settings('buyer',1,%s)", (js(rules),)).fetchone()[0]
                == 2
            )
            assert c.execute("SELECT actor_id FROM policy_changes").fetchone()[0] == "buyer"
        finally:
            c.rollback()


@pytest.mark.parametrize("cap,expected", [("100", "100.00"), ("-0.00", "0.00")])
def test_account_cap_can_be_cleared_without_changing_approval_authority(buyer, cap, expected):
    original = policy_settings.get(buyer)
    saved = policy_settings.update(buyer, change(buyer, max_order_gross=cap))
    assert str(saved["rules"].max_order_gross) == expected
    assert saved["approval_authority"] == original["approval_authority"]
    assert saved["rules"].destinations == original["rules"].destinations
    assert saved["rules"].approved_product_ids == original["rules"].approved_product_ids
    cleared = policy_settings.update(buyer, change(buyer, max_order_gross=None))
    assert cleared["rules"].max_order_gross is None
    assert cleared["approval_authority"] == original["approval_authority"]


@pytest.mark.parametrize("scope", [None, ["retired-product"]])
def test_hidden_scope_is_preserved_even_when_missing_or_outside_active_catalog(buyer, scope):
    with connection() as c:
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) SELECT buyer_id,2,rules || %s FROM policies WHERE buyer_id='demo-hotel' AND version=1",
            (js({"approved_product_ids": scope}),),
        )
        c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    saved = policy_settings.update(buyer, change(buyer, overbuy="allowed"))
    assert saved["rules"].approved_product_ids == scope
    assert saved["rules"].destinations == ["hotel-helsinki"]


def test_lowered_account_cap_blocks_commit_of_previously_confirmed_basket(
    service, buyer, agent, request_data, confirm_terms
):
    from decimal import Decimal

    from aimo.schemas import CommitRequest

    p = service.prepare_order(agent, PrepareRequest(**request_data))
    confirm_terms(p)
    total = Decimal(p["snapshot"]["gross_total"])
    policy_settings.update(buyer, change(buyer, max_order_gross=total - Decimal("0.01")))
    revised = service.commit_order(
        agent, CommitRequest(proposal_id=p["proposal_id"], revision=1, idempotency_key=str(uuid4()))
    )
    assert revised["status"] == "revised" and revised["policy_outcome"] == "denied"
    assert "ACCOUNT_CAP_EXCEEDED" in {r["code"] for r in revised["reasons"]}
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0
