# ruff: noqa: F811  (pytest fixtures re-used from test_recipes are redefined as test arguments)
"""JNP3-DIS-011 and JNP3-DIS-012 (Draft): removing withdrawn products from the stored catalog.

DIS-011: a cleanup function removes withdrawn products that no pending proposal (and no
refreshable recipe proposal) includes. Proposed name: `aimo.ingest.cleanup_withdrawn()`.
DIS-012: when withdrawn products exceed 10 percent of the stored products, the oldest withdrawn
products by withdrawal date are removed. Proposed column: `products.withdrawn_since` (migration
009, not created yet). Proposed function: `aimo.ingest.enforce_withdrawn_limit()` (name assumed).

"Stored products" means the rows of the active generation. Synthetic catalogs through `publish`
with fixture embeddings; the shared fixture catalog and the recipe tables are restored after every
test, and proposals are wiped by the shared `reset_buyers` fixture. Nothing is built yet, so every
test except the controls is a strict xfail.
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


def build_history(service, agent, request_data):
    """A committed order for 464306 and a pending (uncommitted, awaiting approval) one for 464398."""
    done = prepare(service, agent, request_data, "464306")
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
    service, agent, request_data
):
    """Control (passes today): 464306 is in a committed order, 464398 in a pending proposal,
    463380 in none; flagging all three withdrawn leaves them stored and the history readable."""
    receipt, pending = build_history(service, agent, request_data)
    withdrawn = {"464306", "464398", "463380"}
    publish(flagged(fixture_facts(), withdrawn), "dis-011-flagged", "dis-011-flagged-hash")
    rows = active_rows()
    assert all(rows[pid] is True for pid in withdrawn)
    assert service.get_order(agent, receipt["order_id"])["order_status"] == "accepted_mock"
    assert service.get_proposal(agent, pending["proposal_id"])["order_id"] is None


def test_cleanup_keeps_a_withdrawn_product_of_a_pending_proposal(service, agent, request_data):
    """JNP3-DIS-011: cleanup_withdrawn() removes the withdrawn products that no pending proposal
    includes (463380 never ordered, 464306 only in a committed order) and keeps 464398, which a
    pending proposal still names; proposal and order history stay readable."""
    receipt, pending = build_history(service, agent, request_data)
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

# Oldest first by withdrawal date; the ids run the other way so that id order cannot pass the test.
WITHDRAWN_BY_AGE = [("cl-11", 30), ("cl-07", 20), ("cl-03", 10)]


def publish_catalog(total, withdrawn_ids):
    base = fixture_facts()[0]
    data = []
    for number in range(total):
        product = deepcopy(base)
        pid = f"cl-{number:02d}"
        name = f"Cleanup test item {number:02d}"
        product.update(id=pid, name=name, names={"en": name}, deleted=pid in withdrawn_ids)
        product["provenance"] = {"source": "dis-012 test", "product_id": pid}
        data.append(product)
    publish(data, "dis-012-catalog", fingerprint(data))


def set_withdrawal_dates(dated):
    with connection() as c:
        for pid, days_ago in dated:
            c.execute(
                "UPDATE products SET withdrawn_since = now() - make_interval(days => %s) "
                "WHERE id=%s AND generation=(SELECT generation FROM active_catalog)",
                (days_ago, pid),
            )


def test_control_twenty_stored_products_three_withdrawn_is_over_ten_percent():
    """Control (passes today): the synthetic catalog stores 20 products of which 3 are withdrawn."""
    publish_catalog(20, {pid for pid, _ in WITHDRAWN_BY_AGE})
    rows = active_rows()
    assert len(rows) == 20 and sum(rows.values()) == 3
    assert sum(rows.values()) / len(rows) > 0.10


@pytest.mark.xfail(
    strict=True,
    reason="JNP3-DIS-012 Draft: column products.withdrawn_since and the limit rule do not exist",
)
def test_over_ten_percent_removes_the_oldest_withdrawn_until_within_the_limit():
    """JNP3-DIS-012: 3 of 20 stored products are withdrawn (15 percent). After the rule runs, the
    withdrawn products that were removed are the oldest by withdrawn_since (never the newest), live
    products are untouched, and withdrawn products are at most 10 percent of what is stored."""
    publish_catalog(20, {pid for pid, _ in WITHDRAWN_BY_AGE})
    set_withdrawal_dates(WITHDRAWN_BY_AGE)  # UndefinedColumn today
    from aimo.ingest import enforce_withdrawn_limit

    enforce_withdrawn_limit()
    rows = active_rows()
    withdrawn_left = [pid for pid, _ in WITHDRAWN_BY_AGE if pid in rows]
    removed = [pid for pid, _ in WITHDRAWN_BY_AGE if pid not in rows]
    assert removed, "nothing was removed although 15 percent are withdrawn"
    assert removed == [pid for pid, _ in WITHDRAWN_BY_AGE][: len(removed)]  # oldest first
    assert "cl-03" in rows  # the newest withdrawal is never removed first
    assert sum(rows[pid] for pid in withdrawn_left) / len(rows) <= 0.10
    assert sum(1 for pid, flag in rows.items() if not flag) == 17  # live products untouched


@pytest.mark.xfail(
    strict=True,
    reason="JNP3-DIS-012 Draft: column products.withdrawn_since and the limit rule do not exist",
)
def test_at_exactly_ten_percent_nothing_is_removed():
    """JNP3-DIS-012: 2 of 20 stored products withdrawn is exactly 10 percent, not above it, so the
    rule removes nothing."""
    publish_catalog(20, {"cl-11", "cl-07"})
    set_withdrawal_dates([("cl-11", 30), ("cl-07", 20)])  # UndefinedColumn today
    from aimo.ingest import enforce_withdrawn_limit

    enforce_withdrawn_limit()
    rows = active_rows()
    assert len(rows) == 20 and {"cl-11", "cl-07"} <= set(rows)
