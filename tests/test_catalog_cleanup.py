# ruff: noqa: F811  (pytest fixtures re-used from test_recipes are redefined as test arguments)
"""JNP3-DIS-011 and JNP3-DIS-012 (Draft): removing withdrawn products from the stored catalog.

DIS-011: a cleanup function removes withdrawn products that no pending proposal (and no
refreshable recipe proposal) includes. Proposed name: `aimo.ingest.cleanup_withdrawn()`.
DIS-012: when withdrawn products exceed 10 percent of the stored products, the oldest withdrawn
products by withdrawal date are removed: the same cleanup, run at the end of an ingestion publish
(`publish(..., trim_withdrawn=True)`, which `ingest_file` uses), skipping protected products.

"Stored products" means the rows of the active generation. Synthetic catalogs through `publish`
with fixture embeddings; the shared fixture catalog and the recipe tables are restored after every
test, and proposals are wiped by the shared `reset_buyers` fixture.
"""

from copy import deepcopy
from uuid import uuid4

import pytest
from test_recipes import (  # noqa: F401  (fixtures and helpers of the recipe tests)
    actor,
    clean_recipes,
    import_fixture,
    match_all,
    meal_products,
    ref,
    request_for,
)

from aimo import fixtures
from aimo.config import settings
from aimo.db import connection, fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import publish
from aimo.recipe_schemas import ScaleRecipe  # noqa: F401
from aimo.recipes import scale_recipe
from aimo.schemas import CommitRequest, PrepareRequest


@pytest.fixture(autouse=True)
def restore_state():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))
    with connection() as c:
        c.execute(
            "TRUNCATE recipes,recipe_catalogs,recipe_embedding_cache,recipe_product_evidence CASCADE"
        )


def flagged(facts, withdrawn):
    data = deepcopy(facts)
    for p in data:
        if p["id"] in withdrawn:
            p["deleted"] = True
    return data


def active_rows():
    """{id: withdrawn?} for the active generation."""
    with connection() as c:
        return {
            r["id"]: r["deleted"]
            for r in c.execute(
                "SELECT p.id, COALESCE((p.facts->>'deleted')::boolean,false) AS deleted "
                "FROM products p JOIN active_catalog a ON a.generation=p.generation"
            )
        }


def prepare(service, agent, request_data, product_id):
    request_data = request_data | {
        "idempotency_key": str(uuid4()),
        "lines": [{"product_id": product_id, "amount": "10", "unit": "L"}],
    }
    return service.prepare_order(agent, PrepareRequest(**request_data))


# --- DIS-011 -------------------------------------------------------------------------------------


def build_history(service, agent, request_data, confirm_terms):
    """A committed order for 464306 and a pending (uncommitted, awaiting approval) one for 464398."""
    done = prepare(service, agent, request_data, "464306")
    confirm_terms(done)  # every agent role needs a recorded customer confirmation (WS-D)
    receipt = service.commit_order(
        agent,
        CommitRequest(
            proposal_id=done["proposal_id"], revision=done["revision"], idempotency_key=str(uuid4())
        ),
    )
    pending = prepare(service, agent, request_data, "464398")
    assert pending["policy_outcome"] in ("ready_to_commit", "approval_required")
    assert pending["order_id"] is None
    assert pending["approval_status"] not in ("expired", "rejected", "superseded")
    return receipt, pending


def test_control_cleanup_setup_has_one_committed_and_one_pending_proposal(
    service, agent, request_data, confirm_terms
):
    """Control (passes today): 464306 is in a committed order, 464398 in a pending proposal,
    463380 in none; flagging all three withdrawn leaves them stored and the history readable."""
    receipt, pending = build_history(service, agent, request_data, confirm_terms)
    withdrawn = {"464306", "464398", "463380"}
    publish(flagged(fixture_facts(), withdrawn), "dis-011-flagged", "dis-011-flagged-hash")
    rows = active_rows()
    assert all(rows[pid] is True for pid in withdrawn)
    assert service.get_order(agent, receipt["order_id"])["order_status"] == "accepted_mock"
    assert service.get_proposal(agent, pending["proposal_id"])["order_id"] is None


def test_cleanup_keeps_a_withdrawn_product_of_a_pending_proposal(
    service, agent, request_data, confirm_terms
):
    """JNP3-DIS-011: cleanup_withdrawn() removes the withdrawn products that no pending proposal
    includes (463380 never ordered, 464306 only in a committed order) and keeps 464398, which a
    pending proposal still names; proposal and order history stay readable."""
    receipt, pending = build_history(service, agent, request_data, confirm_terms)
    publish(
        flagged(fixture_facts(), {"464306", "464398", "463380"}),
        "dis-011-flagged",
        "dis-011-flagged-hash",
    )
    from aimo.ingest import cleanup_withdrawn

    cleanup_withdrawn()
    rows = active_rows()
    assert "464398" in rows and rows["464398"] is True  # pending proposal: kept, still withdrawn
    assert "463380" not in rows and "464306" not in rows
    assert {"464398", "460123"} <= set(rows)  # live products untouched
    assert service.get_order(agent, receipt["order_id"])["order_status"] == "accepted_mock"
    shown = service.get_proposal(agent, pending["proposal_id"])
    assert shown["proposal_id"] == pending["proposal_id"] and shown["snapshot"]["lines"]


def closed_recipe_proposal(tmp_path, actor, service, monkeypatch):
    """A saved-recipe proposal whose supplier terms expired: closed, not committed, refreshable."""
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", -1)
    first = service.prepare_order(actor, request_for(plan))
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", 900)
    return first


def test_control_a_closed_recipe_proposal_is_tied_to_its_plan_without_an_order(
    tmp_path, actor, service, meal_products, monkeypatch
):
    """Control (passes today): the expired saved-recipe proposal is linked from recipe_plans, has no
    order and is not rejected, i.e. it is refreshable in place; flagging its product keeps the row."""
    first = closed_recipe_proposal(tmp_path, actor, service, monkeypatch)
    assert first["recipe_basis"] == "saved_recipe" and first["approval_status"] == "expired"
    with connection() as c:
        link = c.execute(
            "SELECT p.order_id FROM recipe_plans rp JOIN proposals p ON p.id=rp.proposal_id "
            "WHERE rp.proposal_id=%s",
            (first["proposal_id"],),
        ).fetchone()
    assert link is not None and link["order_id"] is None
    publish(
        flagged(fixtures.fixture_facts(), {"recipe-spaghetti"}),
        "dis-011-recipe-flagged",
        "dis-011-recipe-flagged-hash",
    )
    assert active_rows()["recipe-spaghetti"] is True


def test_cleanup_keeps_a_withdrawn_product_of_a_refreshable_recipe_proposal(
    tmp_path, actor, service, meal_products, monkeypatch
):
    """JNP3-DIS-011 (reworded): a withdrawn product named by a recipe proposal that is closed but
    refreshable (tied to a recipe plan, no order, not rejected) is kept by cleanup_withdrawn();
    a withdrawn product that no proposal names (463380) is removed."""
    first = closed_recipe_proposal(tmp_path, actor, service, monkeypatch)
    publish(
        flagged(fixtures.fixture_facts(), {"recipe-spaghetti", "463380"}),
        "dis-011-recipe-flagged",
        "dis-011-recipe-flagged-hash",
    )
    from aimo.ingest import cleanup_withdrawn

    cleanup_withdrawn()
    rows = active_rows()
    assert rows.get("recipe-spaghetti") is True  # refreshable recipe proposal: kept
    assert "463380" not in rows
    assert service.get_proposal(actor, first["proposal_id"])["snapshot"]["lines"]


# --- DIS-012 -------------------------------------------------------------------------------------


def catalog(total, withdrawn_ids):
    base = fixture_facts()[0]
    data = []
    for number in range(total):
        product = deepcopy(base)
        pid = f"cl-{number:02d}"
        name = f"Cleanup test item {number:02d}"
        product.update(id=pid, name=name, names={"en": name}, deleted=pid in withdrawn_ids)
        product["provenance"] = {"source": "dis-012 test", "product_id": pid}
        data.append(product)
    return data


def publish_trimmed(data):
    return publish(data, "dis-012-catalog", fingerprint(data) + str(uuid4()), trim_withdrawn=True)


def age(dated):
    """Back-date withdrawals in the active generation: {id: days ago}."""
    with connection() as c:
        for pid, days_ago in dated.items():
            c.execute(
                "UPDATE products SET withdrawn_since = now() - make_interval(days => %s) "
                "WHERE id=%s AND generation=(SELECT generation FROM active_catalog)",
                (days_ago, pid),
            )


def test_at_exactly_ten_percent_nothing_is_removed():
    """JNP3-DIS-012: 2 of 20 stored products withdrawn is exactly 10 percent, not above it."""
    result = publish_trimmed(catalog(20, {"cl-11", "cl-07"}))
    rows = active_rows()
    assert len(rows) == 20 and {"cl-11", "cl-07"} <= set(rows) and result["trimmed_withdrawn"] == 0


def test_over_ten_percent_removes_the_oldest_withdrawn_one_at_a_time_until_within_the_limit():
    """JNP3-DIS-012: a third withdrawal (3 of 20 = 15 percent) removes the oldest by withdrawn_since
    first (cl-11, then cl-07 because 2 of 19 is still above 10 percent), keeps the newest (cl-03) and
    leaves live products untouched. The ids run against the ages so id order cannot pass."""
    publish_trimmed(catalog(20, {"cl-11"}))
    age({"cl-11": 30})
    publish_trimmed(
        catalog(20, {"cl-11", "cl-07"})
    )  # first withdrawal date carried: cl-11 stays old
    age({"cl-07": 20})
    result = publish_trimmed(catalog(20, {"cl-11", "cl-07", "cl-03"}))
    rows = active_rows()
    assert result["trimmed_withdrawn"] == 2
    assert "cl-11" not in rows and "cl-07" not in rows and rows["cl-03"] is True
    assert sum(1 for flag in rows.values() if not flag) == 17
    assert sum(rows.values()) / len(rows) <= 0.10
    with connection() as c:  # the generation stays re-activatable
        count = c.execute(
            "SELECT g.product_count, (SELECT count(*) FROM products p WHERE p.generation=g.id) AS n "
            "FROM catalog_generations g JOIN active_catalog a ON a.generation=g.id"
        ).fetchone()
    assert count["product_count"] == count["n"] == 18


def test_a_protected_withdrawn_product_is_skipped_and_the_next_oldest_goes(
    service, agent, request_data
):
    """JNP3-DIS-012 with DIS-011: the oldest withdrawn product (464306) is named by a pending
    proposal, so the rule skips it and removes the next oldest ones until within 10 percent."""
    pending = prepare(service, agent, request_data, "464306")
    assert pending["order_id"] is None
    extras = [
        dict(fixture_facts()[0], id=f"cl-x{n:02d}", name=f"Filler {n}", names={"en": f"Filler {n}"})
        for n in range(30)
    ]
    withdrawn = ["464306", "464398", "463380", "465039", "460123"]  # oldest first
    data = flagged(fixture_facts(), set(withdrawn)) + extras
    publish(data, "dis-012-protected", fingerprint(data) + str(uuid4()))
    age({pid: 50 - number for number, pid in enumerate(withdrawn)})
    result = publish_trimmed(data)
    rows = active_rows()
    assert result["trimmed_withdrawn"] == 2
    assert rows["464306"] is True  # protected, though the oldest
    assert "464398" not in rows and "463380" not in rows
    assert {"465039", "460123"} <= set(rows)


def test_an_ingest_with_nothing_withdrawn_trims_nothing():
    """JNP3-DIS-012: the automatic rule never deletes data when no product is withdrawn."""
    result = publish_trimmed(catalog(20, set()))
    assert result["trimmed_withdrawn"] == 0 and result["withdrawn_products"] == 0
    assert len(active_rows()) == 20


def test_the_trim_skips_a_withdrawn_product_of_a_refreshable_recipe_proposal(
    tmp_path, actor, service, meal_products, monkeypatch
):
    """JNP3-DIS-012 with the owner's protection rule (Q-36): the oldest withdrawn product
    (recipe-spaghetti) belongs to a closed but refreshable saved-recipe proposal, so the automatic
    trim keeps it and removes the next oldest withdrawn products instead."""
    first = closed_recipe_proposal(tmp_path, actor, service, monkeypatch)
    extras = [
        dict(fixtures.fixture_facts()[0], id=f"cl-x{n:02d}", name=f"F {n}", names={"en": f"F {n}"})
        for n in range(30)
    ]
    withdrawn = ["recipe-spaghetti", "463380", "464398", "465039", "460123", "460035"]
    data = flagged(fixtures.fixture_facts(), set(withdrawn)) + extras
    publish(data, "dis-012-recipe", fingerprint(data) + str(uuid4()))
    age({pid: 60 - number for number, pid in enumerate(withdrawn)})
    result = publish_trimmed(data)
    rows = active_rows()
    assert result["trimmed_withdrawn"] == 2
    assert rows["recipe-spaghetti"] is True  # protected though the oldest
    assert "463380" not in rows and "464398" not in rows
    assert service.get_proposal(actor, first["proposal_id"])["snapshot"]["lines"]
