"""WS-B audit tests for PER-001 (persistence), PER-003 (read by ID and revision), PER-004 (append-only).

Local audit file. Passing tests pin behaviour that exists today. Strict xfail tests
mark gaps where an API exists to call and does not do what the requirement needs.
PER-003 is satisfied by the current revision plus the revision a proposal was prepared
from (owner decision Q-46: that is enough); reading a past revision by number is not
required, so no test demands it. PER-004 (Draft, Q-47): recipe plan revisions and recipe
versions are append-only in the database; the one gap is a strict xfail below.
Authored fixtures only, no supplier call. Helpers are copied from test_recipes.py.
"""

import hashlib
import json
import os
from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from aimo import approval_workflow as workflow
from aimo import conversations, fixtures
from aimo.agent_tools import ToolSession
from aimo.api import create_app
from aimo.auth import internal_agent
from aimo.chat_schemas import AgentTurn, ConversationCreate, MealPlan, MessageRequest
from aimo.config import settings
from aimo.db import Problem, close_pools, connection, fingerprint, js
from aimo.ingest import publish
from aimo.recipe_import import import_product_evidence, ingest_recipes
from aimo.recipe_schemas import MatchIngredient, PlanReference, ScaleRecipe
from aimo.recipes import get_plan, match_ingredient, scale_recipe
from aimo.schemas import CommitRequest, PrepareRequest
from aimo.service import Service
from aimo.upstream import FixtureClient

# ---------------------------------------------------------------------------
# Helpers copied from tests/test_recipes.py (authored recipe, products, evidence)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_recipes():
    with connection() as c:
        # A recipe reset cascades into guarded history (PER-002): say it is deliberate.
        c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        c.execute(
            "TRUNCATE recipes,recipe_catalogs,recipe_embedding_cache,recipe_product_evidence CASCADE"
        )
    yield


def write(path, data):
    path.write_text(json.dumps(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_recipe(slug="carbonara"):
    # Authored minimal recipe for pipeline testing, not the public UniTools recipe.
    return {
        "slug": slug,
        "name": {"en": "Authored " + slug},
        "summary": {"en": "Pasta meal"},
        "baseServings": 2,
        "category": "main",
        "steps": [{"text": {"en": "Cook the meal."}}],
        "ingredients": [
            {
                "id": "spaghetti",
                "name": {"en": "Dry spaghetti"},
                "quantity": 200,
                "unit": "g",
                "scaling": "linear",
            },
            {
                "id": "egg",
                "name": {"en": "Raw whole eggs"},
                "quantity": 1,
                "unit": "piece",
                "scaling": "linear",
            },
            {
                "id": "pepper",
                "name": {"en": "Black pepper"},
                "quantity": 2,
                "unit": "g",
                "scaling": "linear",
            },
        ],
    }


def import_fixture(tmp_path, rows=None, review=True):
    rows = rows or [source_recipe()]
    path = tmp_path / "recipes.json"
    sha = write(
        path,
        {
            "license": "CC BY-SA 4.0",
            "version": "authored-test-v1",
            "attribution": "Authored test fixture",
            "recipes": rows,
        },
    )
    reviews = tmp_path / "reviews.json"
    write(
        reviews,
        {
            "source": "Authored test recipe review",
            "recipes": {
                row["slug"]: {
                    "ingredients": {
                        i["id"]: {"form": "raw" if i["id"] == "egg" else "dry"}
                        for i in row["ingredients"]
                    }
                }
                for row in rows
            },
        },
    )
    result = ingest_recipes(path, sha, reviews if review else None)
    with connection() as c:
        versions = c.execute(
            "SELECT recipe_id,version FROM recipe_catalog_entries WHERE catalog_id=%s ORDER BY recipe_id",
            (result["catalog_id"],),
        ).fetchall()
    return path, sha, reviews if review else None, result, versions


@pytest.fixture
def actor(agent):
    return agent | {"_turn_id": str(uuid4())}


@pytest.fixture
def internal(buyer):
    """The buyer's internal agent, as the chat worker uses it."""
    return internal_agent(buyer) | {"_turn_id": str(uuid4())}


def ref(versions, portions=200):
    return ScaleRecipe(**versions[0], portions=portions)


@pytest.fixture
def meal_products(monkeypatch, tmp_path):
    original = fixtures.fixture_facts()
    products = []
    for iid, weight in [("spaghetti", "3"), ("egg", "1"), ("pepper", ".21")]:
        p = deepcopy(original[0])
        p.update(
            id="recipe-" + iid,
            name="Authored " + iid,
            names={"en": "Authored " + iid},
            sales_unit="ST",
            base_unit="ST",
            units={"ST": "1"},
            order_step=".01",
            variable_weight=False,
            deposits=[],
            allergens={},
            claims=[],
            free_from=[],
            measures={
                "KG": {"status": "known", "value": weight, "basis": ["authored.structured.weight"]},
                "L": {"status": "unknown", "value": None, "basis": []},
            },
        )
        products.append(p)
    monkeypatch.setattr(fixtures, "fixture_facts", lambda: original + products)
    publish(original + products, "authored-recipe-products", fingerprint(products))
    rows = [
        dict(
            product_id=p["id"],
            product_fingerprint=fingerprint(p),
            ingredient_id=iid,
            form="raw" if iid == "egg" else "dry",
            source="Authored reviewed product evidence",
            piece_per_sales="30" if iid == "egg" else None,
        )
        for iid, p in zip(["spaghetti", "egg", "pepper"], products)
    ]
    evidence = tmp_path / "evidence.json"
    write(evidence, rows)
    import_product_evidence(evidence)
    yield products, evidence
    publish(original, "restore-standard-fixtures", fingerprint(original))


def match_all(actor, plan):
    for item in list(plan["ingredients"]):
        plan = match_ingredient(
            actor,
            MatchIngredient(
                plan_id=plan["recipe_plan_id"],
                revision=plan["recipe_plan_revision"],
                ingredient_id=item["ingredient_id"],
                product_id="recipe-" + item["ingredient_id"],
            ),
        )
    return plan


def request_for(plan):
    return PrepareRequest(
        recipe_plan_id=plan["recipe_plan_id"],
        recipe_plan_revision=plan["recipe_plan_revision"],
        request_id="Authored recipe for 200",
        idempotency_key=str(uuid4()),
        destination="hotel-helsinki",
        delivery_date=date.today() + timedelta(days=2),
        budget_gross="1000",
        lines=[
            {
                "product_id": i["product_id"],
                "amount": i["purchase_amount"],
                "unit": i["purchase_unit"],
            }
            for i in plan["ingredients"]
            if i["status"] == "matched"
        ],
    )


# ---------------------------------------------------------------------------
# Helpers new in this file
# ---------------------------------------------------------------------------


@pytest.fixture
def planned(tmp_path, actor, meal_products):
    """A saved, fully matched plan (revision 4: scale, then one match per ingredient)."""
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    assert plan["recipe_plan_revision"] == 4
    return plan, versions


@pytest.fixture
def internal_planned(tmp_path, internal, meal_products):
    """Same plan, saved by the buyer's internal agent (the identity the chat worker uses)."""
    *_, versions = import_fixture(tmp_path)
    plan = match_all(internal, scale_recipe(internal, ref(versions)))
    assert plan["recipe_plan_revision"] == 4
    return plan, versions


def restart_pool_and_service():
    """Drop every pooled connection and build a new Service: the nearest in-process restart."""
    close_pools()
    return Service(FixtureClient())


def signed(client):
    result = client.post(
        "/api/login",
        headers={"Origin": "http://testserver"},
        json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
    )
    assert result.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": result.json()["csrf_token"]}


def refreshed_proposal(actor, service, plan, monkeypatch):
    """Two revisions of one proposal: an expired first revision, refreshed by a later turn."""
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", -1)
    first = service.prepare_order(actor, request_for(plan))
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", 900)
    later = actor | {"_turn_id": str(uuid4())}
    saved = get_plan(later, PlanReference(plan_id=plan["recipe_plan_id"]))
    second = service.prepare_order(later, request_for(saved))
    assert (first["revision"], second["revision"]) == (1, 2)
    assert first["proposal_id"] == second["proposal_id"]
    return first, second


def add_identity(identity_id, buyer_id, role, authority):
    with connection() as c:
        c.execute(
            "INSERT INTO identities VALUES(%s,%s,%s,true,%s,%s)",
            (identity_id, buyer_id, role, "!test-no-login", js(authority)),
        )
        return c.execute("SELECT * FROM identities WHERE id=%s", (identity_id,)).fetchone()


# ===========================================================================
# PER-001: persist meal and selection evidence and confirmation records
# ===========================================================================


def test_plan_revisions_selection_and_conversion_survive_pool_restart(planned, actor):
    plan, _ = planned
    pid = plan["recipe_plan_id"]
    restart_pool_and_service()
    with connection() as c:
        header = c.execute("SELECT * FROM recipe_plans WHERE id=%s", (pid,)).fetchone()
        revisions = c.execute(
            "SELECT revision,data FROM recipe_plan_revisions WHERE plan_id=%s ORDER BY revision",
            (pid,),
        ).fetchall()
    assert (header["revision"], header["portions"], header["locked"]) == (4, 200, False)
    assert [r["revision"] for r in revisions] == [1, 2, 3, 4]
    # Selections and conversion evidence live inside the revision JSON, one product per ingredient.
    stored = {i["ingredient_id"]: i for i in revisions[-1]["data"]["ingredients"]}
    assert {k: v["product_id"] for k, v in stored.items()} == {
        "spaghetti": "recipe-spaghetti",
        "egg": "recipe-egg",
        "pepper": "recipe-pepper",
    }
    assert stored["egg"]["conversion"]["sales_quantity"] == "4"
    assert stored["egg"]["conversion"]["excess"] == "20"
    assert all(i["product_fingerprint"] and i["status"] == "matched" for i in stored.values())
    # Revision 1 still holds the pre-selection state (history is kept, not overwritten).
    assert all(i["product_id"] is None for i in revisions[0]["data"]["ingredients"])
    assert get_plan(actor, PlanReference(plan_id=pid)) == plan


def test_recipe_version_source_attribution_and_product_evidence_persisted(planned, actor):
    plan, versions = planned
    restart_pool_and_service()
    with connection() as c:
        version = c.execute(
            "SELECT * FROM recipe_versions WHERE recipe_id=%s AND version=%s",
            (versions[0]["recipe_id"], versions[0]["version"]),
        ).fetchone()
        evidence = c.execute(
            "SELECT product_id,ingredient_id,form,piece_per_sales FROM recipe_product_evidence "
            "ORDER BY ingredient_id"
        ).fetchall()
        header = c.execute(
            "SELECT recipe_id,recipe_version FROM recipe_plans WHERE id=%s",
            (plan["recipe_plan_id"],),
        ).fetchone()
    assert version["attribution"] == "Authored test fixture"
    assert version["license"] == "CC BY-SA 4.0"
    assert version["source_hash"] and version["source_version"] == "authored-test-v1"
    assert version["data"]["base_servings"] == 2
    # The plan points at the exact immutable-by-convention recipe version it was scaled from.
    assert (header["recipe_id"], header["recipe_version"]) == (
        versions[0]["recipe_id"],
        versions[0]["version"],
    )
    assert plan["attribution"] == "Authored test fixture / CC BY-SA 4.0"
    assert [(e["product_id"], e["ingredient_id"]) for e in evidence] == [
        ("recipe-egg", "egg"),
        ("recipe-pepper", "pepper"),
        ("recipe-spaghetti", "spaghetti"),
    ]


def test_proposal_revisions_approval_confirmation_and_order_survive_pool_restart(
    internal_planned, internal, buyer, service
):
    plan, _ = internal_planned
    prepared = service.prepare_order(internal, request_for(plan))
    assert prepared["approval_status"] == "pending"
    commit = CommitRequest(
        proposal_id=prepared["proposal_id"], revision=1, idempotency_key=str(uuid4())
    )
    receipt = conversations.confirm(buyer, prepared["proposal_id"], commit, service)
    assert receipt["status"] == "accepted_mock"

    fresh = restart_pool_and_service()
    pid = prepared["proposal_id"]
    with connection() as c:
        revision = c.execute(
            "SELECT * FROM proposal_revisions WHERE proposal_id=%s", (pid,)
        ).fetchone()
        approval = c.execute("SELECT * FROM approvals WHERE proposal_id=%s", (pid,)).fetchone()
        confirmation = c.execute(
            "SELECT * FROM customer_confirmations WHERE proposal_id=%s", (pid,)
        ).fetchone()
        order = c.execute("SELECT * FROM orders WHERE proposal_id=%s", (pid,)).fetchone()
        events = [
            e["event"]
            for e in c.execute(
                "SELECT event FROM audit_events WHERE proposal_id=%s ORDER BY id", (pid,)
            ).fetchall()
        ]
    assert revision["request"]["recipe_plan_id"] == plan["recipe_plan_id"]
    assert revision["snapshot"]["gross_total"] == prepared["snapshot"]["gross_total"]
    assert approval["status"] == "approved" and approval["actor_id"] == buyer["id"]
    assert confirmation["fingerprint"] == revision["fingerprint"]
    assert confirmation["actor_id"] == buyer["id"]
    assert order["receipt"]["status"] == "accepted_mock"
    assert {"proposal_prepared", "customer_confirmed", "approved", "accepted_mock"} <= set(events)
    # The same facts come back through the public read paths of a new Service.
    again = fresh.get_proposal(internal, pid)
    assert again["order_id"] == str(order["id"]) and again["order_status"] == "accepted_mock"
    assert fresh.get_order(internal, str(order["id"])) == receipt


def test_conversation_message_keeps_meal_plan_and_proposal_link_across_restart(
    internal_planned, buyer, service, monkeypatch
):
    plan, versions = internal_planned

    def runner(agent_identity, history, shared):
        # Authored stand-in for the model: the same plan the test saved, prepared once.
        saved = get_plan(agent_identity, PlanReference(plan_id=plan["recipe_plan_id"]))
        prepared = shared.prepare_order(agent_identity, request_for(saved))
        return AgentTurn(
            text="Review this basket.",
            meal_plan=MealPlan.model_validate(saved),
            proposal_id=prepared["proposal_id"],
        )

    conversation = conversations.create(
        buyer, ConversationCreate(title="Carbonara", idempotency_key=str(uuid4()))
    )
    conversations.message(
        buyer,
        conversation["id"],
        MessageRequest(text="200 portions of carbonara", idempotency_key=str(uuid4())),
        service,
        runner,
    )
    restart_pool_and_service()
    with connection() as c:
        row = c.execute(
            "SELECT meal_plan,proposal_id FROM conversation_messages "
            "WHERE conversation_id=%s AND role='assistant'",
            (conversation["id"],),
        ).fetchone()
    assert row["meal_plan"]["recipe_plan_id"] == plan["recipe_plan_id"]
    assert row["meal_plan"]["recipe_plan_revision"] == plan["recipe_plan_revision"]
    assert row["meal_plan"]["ingredients"][1]["conversion"]["sales_quantity"] == "4"
    detail = conversations.detail(buyer, conversation["id"])
    assert [p["proposal_id"] for p in detail["purchases"]] == [str(row["proposal_id"])]


@pytest.mark.parametrize("table", ["proposal_revisions", "customer_confirmations", "audit_events"])
def test_history_tables_reject_update_and_delete(internal_planned, internal, buyer, service, table):
    plan, _ = internal_planned
    prepared = service.prepare_order(internal, request_for(plan))
    conversations.confirm(
        buyer,
        prepared["proposal_id"],
        CommitRequest(
            proposal_id=prepared["proposal_id"], revision=1, idempotency_key=str(uuid4())
        ),
        service,
    )
    sets = {
        "proposal_revisions": "fingerprint='x'",
        "customer_confirmations": "fingerprint='x'",
        "audit_events": "event='x'",
    }
    for statement in (f"UPDATE {table} SET {sets[table]}", f"DELETE FROM {table}"):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
            with connection() as c:
                c.execute(statement)


# PER-004 (Approved): migration 019 guards recipe_plan_revisions and recipe_versions.
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE recipe_plan_revisions SET data='{}'::jsonb",
        "DELETE FROM recipe_plan_revisions",
        "UPDATE recipe_versions SET attribution='tampered'",
        "DELETE FROM recipe_versions",
    ],
)
def test_per_004_plan_revisions_and_recipe_versions_are_append_only_in_database(planned, statement):
    with pytest.raises(psycopg.errors.RaiseException, match="immutable history"):
        with connection() as c:
            c.execute(statement)


def test_failed_prepare_rolls_back_every_proposal_record_and_keeps_the_plan(
    planned, actor, service, monkeypatch
):
    plan, _ = planned
    monkeypatch.setattr(
        workflow,
        "render",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Authored failure before commit")),
    )
    with pytest.raises(RuntimeError, match="Authored failure"):
        service.prepare_order(actor, request_for(plan))
    with connection() as c:
        counts = {
            table: c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "proposals",
                "proposal_revisions",
                "approvals",
                "audit_events",
                "prepare_requests",
            )
        }
        locked = c.execute("SELECT locked, proposal_id FROM recipe_plans").fetchone()
        revisions = c.execute("SELECT count(*) AS n FROM recipe_plan_revisions").fetchone()["n"]
    assert counts == dict.fromkeys(counts, 0)
    assert locked == {"locked": False, "proposal_id": None}
    # Nothing the buyer already saved is lost: the four plan revisions and the plan itself remain.
    assert revisions == 4
    assert get_plan(actor, PlanReference(plan_id=plan["recipe_plan_id"])) == plan


def test_tool_session_state_is_memory_only_and_the_plan_reloads_from_postgres(
    tmp_path, actor, service, meal_products
):
    *_, versions = import_fixture(tmp_path)
    session = ToolSession(actor, service)

    def call(s, name, args):
        return s.invoke(name, json.dumps(args))

    plan = call(session, "scale_recipe", dict(versions[0], portions=200))["meal_plan"]
    for item in plan["ingredients"]:
        call(session, "get_product", {"product_id": "recipe-" + item["ingredient_id"]})
        plan = call(
            session,
            "match_ingredient",
            dict(
                plan_id=plan["recipe_plan_id"],
                revision=plan["recipe_plan_revision"],
                ingredient_id=item["ingredient_id"],
                product_id="recipe-" + item["ingredient_id"],
            ),
        )["meal_plan"]
    assert session.plan is not None and len(session.products) == 3

    # A new turn builds a new ToolSession: verified products, plan and proposal are gone.
    next_turn = ToolSession(actor | {"_turn_id": str(uuid4())}, service)
    assert next_turn.plan is None and next_turn.products == {} and next_turn.proposal is None
    with pytest.raises(Problem) as error:
        call(
            next_turn,
            "match_ingredient",
            dict(
                plan_id=plan["recipe_plan_id"],
                revision=plan["recipe_plan_revision"],
                ingredient_id="pepper",
                product_id="recipe-pepper",
            ),
        )
    assert error.value.code == "PRODUCT_NOT_VERIFIED"
    # What survives is only what was written to the database.
    assert (
        call(next_turn, "get_recipe_plan", {"plan_id": plan["recipe_plan_id"]})["meal_plan"] == plan
    )
    assert next_turn.plan.model_dump(mode="json") == plan


# ===========================================================================
# PER-003: expose meal plans and proposals by ID and revision
# ===========================================================================


def test_plan_by_id_returns_the_current_revision_and_names_its_number(planned, actor):
    plan, _ = planned
    current = get_plan(actor, PlanReference(plan_id=plan["recipe_plan_id"]))
    assert current["recipe_plan_id"] == plan["recipe_plan_id"]
    assert current["recipe_plan_revision"] == 4
    with pytest.raises(Problem) as error:
        get_plan(actor, PlanReference(plan_id=uuid4()))
    assert error.value.code == "NOT_FOUND"


def test_service_get_recipe_plan_matches_the_recipes_module(planned, actor, service):
    plan, _ = planned
    request = PlanReference(plan_id=plan["recipe_plan_id"])
    assert service.get_recipe_plan(actor, request) == plan


def test_proposal_carries_server_computed_totals_and_http_returns_them_unchanged(
    planned, actor, service
):
    plan, _ = planned
    prepared = service.prepare_order(actor, request_for(plan))
    with TestClient(create_app(service)) as client:
        signed(client)
        response = client.get(f"/api/purchases/{prepared['proposal_id']}")
        assert response.status_code == 200, response.text
        body = response.json()
    with connection() as c:
        stored = c.execute(
            "SELECT snapshot FROM proposal_revisions WHERE proposal_id=%s",
            (prepared["proposal_id"],),
        ).fetchone()["snapshot"]
    snapshot = body["snapshot"]
    assert snapshot["gross_total"] == stored["gross_total"] == prepared["snapshot"]["gross_total"]
    assert snapshot["net_total"] == stored["net_total"]
    assert snapshot["tax_total"] == stored["tax_total"]
    assert snapshot["currency"] == "EUR"
    # A client need not recompute: the total equals the line prices plus deposits the server already gave.
    from decimal import Decimal

    lines = snapshot["lines"]
    assert sum(Decimal(x["gross"]) + Decimal(x["deposits_gross"]) for x in lines) == Decimal(
        snapshot["gross_total"]
    )
    assert body["revision"] == body["current_revision"] == 1
    assert body["request"]["recipe_plan_id"] == plan["recipe_plan_id"]


def test_proposal_and_plan_reference_each_other_by_id_and_revision(planned, actor, service):
    plan, _ = planned
    prepared = service.prepare_order(actor, request_for(plan))
    assert prepared["recipe_basis"] == "saved_recipe"
    assert prepared["request"]["recipe_plan_id"] == plan["recipe_plan_id"]
    assert prepared["request"]["recipe_plan_revision"] == plan["recipe_plan_revision"]
    with connection() as c:
        link = c.execute(
            "SELECT proposal_id,locked,revision FROM recipe_plans WHERE id=%s",
            (plan["recipe_plan_id"],),
        ).fetchone()
    assert str(link["proposal_id"]) == prepared["proposal_id"] and link["locked"]
    # Locked: the plan can no longer gain revisions, so the referenced revision stays the current one.
    assert link["revision"] == prepared["request"]["recipe_plan_revision"]
    assert get_plan(actor, PlanReference(plan_id=plan["recipe_plan_id"])) == plan


def test_old_proposal_revision_is_readable_through_its_approval_id(
    planned, actor, service, monkeypatch
):
    plan, _ = planned
    first, second = refreshed_proposal(actor, service, plan, monkeypatch)
    assert first["approval_id"] and second["approval_id"] != first["approval_id"]
    current = service.get_proposal(actor, first["proposal_id"])
    assert current["revision"] == current["current_revision"] == 2
    with TestClient(create_app(service)) as client:
        signed(client)
        old = client.get(f"/api/approvals/{first['approval_id']}")
        assert old.status_code == 200, old.text
    body = old.json()
    assert body["revision"] == 1 and body["current_revision"] == 2
    assert body["approval_status"] == "superseded"
    assert body["next_action"]["type"] == "view_current_proposal"
    assert body["snapshot"]["gross_total"] == first["snapshot"]["gross_total"]
    assert body["revision"] != second["revision"]


def test_scoping_other_buyer_other_agent_and_same_buyer_approver(planned, actor, service):
    plan, _ = planned
    prepared = service.prepare_order(actor, request_for(plan))
    rules = {"currency": "EUR", "autonomous_limit": "1500.00"}
    sibling = add_identity("second-agent", "demo-hotel", "agent", rules)
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other-hotel','456',1)")
        policy = c.execute(
            "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
        ).fetchone()["rules"]
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('other-hotel',1,%s)", (js(policy),)
        )
    stranger = add_identity("other-agent", "other-hotel", "agent", rules)
    stranger_approver = add_identity(
        "other-buyer",
        "other-hotel",
        "approver",
        {"currency": "EUR", "max_gross": "5000.00", "exceptions": []},
    )
    plan_ref = PlanReference(plan_id=plan["recipe_plan_id"])
    for outsider in (sibling | {"_turn_id": "t"}, stranger | {"_turn_id": "t"}):
        with pytest.raises(Problem) as error:
            get_plan(outsider, plan_ref)
        assert error.value.code == "NOT_FOUND"
        with pytest.raises(Problem) as error:
            service.get_proposal(outsider, prepared["proposal_id"])
        assert error.value.code == "NOT_FOUND"
    with pytest.raises(Problem) as error:
        service.get_proposal(stranger_approver, prepared["proposal_id"])
    assert error.value.code == "NOT_FOUND"
    # Current behaviour, recorded so a change is deliberate: the same buyer's approver reads the
    # proposal but cannot read the plan by ID, because read_plan filters on the creating agent.
    with connection() as c:
        approver = c.execute("SELECT * FROM identities WHERE id='buyer'").fetchone()
    assert (
        service.get_proposal(approver, prepared["proposal_id"])["proposal_id"]
        == (prepared["proposal_id"])
    )
    with pytest.raises(Problem) as error:
        get_plan(approver, plan_ref)
    assert error.value.code == "NOT_FOUND"


def test_conversation_meal_plan_copy_is_labelled_but_goes_stale_after_a_later_revision(
    internal_planned, buyer, service, monkeypatch
):
    # About the stored copy, not the cart: with auto-prepare a fully matched saved recipe plan is
    # prepared (and so locked) after the first turn, which blocks the re-match this test performs
    # (Q-126: whether edits to a locked recipe basket become new revisions).
    from aimo.config import settings

    monkeypatch.setattr(settings(), "cart_auto_prepare", False)
    plan, _ = internal_planned
    pid = plan["recipe_plan_id"]

    def first_turn(agent_identity, history, shared):
        return AgentTurn(text="Plan saved.", meal_plan=MealPlan.model_validate(plan))

    def second_turn(agent_identity, history, shared):
        # A later customer message re-matches one ingredient: the authoritative plan moves on.
        newer = match_ingredient(
            agent_identity,
            MatchIngredient(
                plan_id=pid,
                revision=plan["recipe_plan_revision"],
                ingredient_id="pepper",
                product_id="recipe-pepper",
            ),
        )
        return AgentTurn(text="Re-matched.", meal_plan=MealPlan.model_validate(newer))

    conversation = conversations.create(
        buyer, ConversationCreate(title="Carbonara", idempotency_key=str(uuid4()))
    )
    for text, runner in (("plan it", first_turn), ("change pepper", second_turn)):
        conversations.message(
            buyer,
            conversation["id"],
            MessageRequest(text=text, idempotency_key=str(uuid4())),
            service,
            runner,
        )
    with connection() as c:
        copies = [
            r["meal_plan"]
            for r in c.execute(
                "SELECT meal_plan FROM conversation_messages WHERE conversation_id=%s "
                "AND role='assistant' ORDER BY id",
                (conversation["id"],),
            ).fetchall()
        ]
        authoritative = c.execute(
            "SELECT revision FROM recipe_plans WHERE id=%s", (pid,)
        ).fetchone()["revision"]
    assert [c["recipe_plan_revision"] for c in copies] == [4, 5]
    assert authoritative == 5
    # The first message still shows revision 4: a stale copy, but it carries its own revision number,
    # so a consumer can detect the drift. No total or proposal snapshot is copied into the message.
    assert copies[0]["recipe_plan_revision"] < authoritative
    assert all("gross_total" not in json.dumps(c) for c in copies)


def test_per_003_proposal_names_the_plan_revision_it_was_prepared_from_and_that_row_stays_readable(
    planned, actor, service
):
    """Q-46: the revision a proposal was prepared from is enough (no read-by-number API)."""
    plan, _ = planned
    pid = plan["recipe_plan_id"]
    prepared = service.prepare_order(actor, request_for(plan))
    assert prepared["request"]["recipe_plan_id"] == pid
    assert prepared["request"]["recipe_plan_revision"] == plan["recipe_plan_revision"] == 4
    restart_pool_and_service()
    with connection() as c:
        stored = c.execute(
            "SELECT data FROM recipe_plan_revisions WHERE plan_id=%s AND revision=%s",
            (pid, prepared["request"]["recipe_plan_revision"]),
        ).fetchone()
        revisions = [
            r["revision"]
            for r in c.execute(
                "SELECT revision FROM recipe_plan_revisions WHERE plan_id=%s ORDER BY revision",
                (pid,),
            ).fetchall()
        ]
    # The plan advanced through revisions 1 to 4 before the proposal was prepared, and the
    # revision the proposal names is still stored, equal to what the agent saw.
    assert revisions == [1, 2, 3, 4]
    assert stored["data"] == plan
