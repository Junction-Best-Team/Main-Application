"""Recipe import/planning against PostgreSQL; authored recipe/catalog/commerce fixtures."""

import hashlib
import json
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from aimo import fixtures, recipe_search
from aimo.agent_tools import ToolSession
from aimo.config import settings
from aimo.db import Problem, close_pools, connection, fingerprint, js
from aimo.ingest import publish
from aimo.recipe_import import import_product_evidence, ingest_recipes
from aimo.recipe_schemas import (
    MatchIngredient,
    PlanReference,
    RecipeReference,
    RecipeSearch,
    ScaleRecipe,
)
from aimo.recipes import get_plan, get_recipe, match_ingredient, scale_recipe, search_recipes
from aimo.schemas import PrepareRequest


@pytest.fixture(autouse=True)
def clean_recipes():
    with connection() as c:
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


def ref(versions, portions=200):
    return ScaleRecipe(**versions[0], portions=portions)


def test_import_idempotence_checksum_versions_and_search(tmp_path, actor):
    path, sha, review, result, versions = import_fixture(tmp_path)
    again = ingest_recipes(path, sha, review)
    assert again["catalog_id"] == result["catalog_id"] and again["embedded"] == 0
    found = search_recipes(actor, RecipeSearch(query="carbonara"))
    assert found["recipes"][0]["recipe_id"] == "unitools:carbonara"
    assert (
        search_recipes(actor, RecipeSearch(query="carbonara", category="dessert"))["recipes"] == []
    )
    original = get_recipe(actor, RecipeReference(**versions[0]))
    raw = json.loads(path.read_text())
    raw["recipes"][0]["ingredients"][0]["quantity"] = 250
    sha2 = write(path, raw)
    updated = ingest_recipes(path, sha2, review)
    assert updated["catalog_id"] != result["catalog_id"]
    assert get_recipe(actor, RecipeReference(**versions[0])) == original
    with pytest.raises(ValueError, match="checksum"):
        ingest_recipes(path, sha, review)


def test_import_resumes_paid_batches_without_publishing_partial_catalog(
    tmp_path, actor, monkeypatch
):
    _, _, _, original, _ = import_fixture(tmp_path)
    rows = [source_recipe("dish-" + str(i)) for i in range(35)]
    # Generate only files; inject a failure after one new complete batch.
    path = tmp_path / "many.json"
    sha = write(
        path,
        {
            "license": "CC BY-SA 4.0",
            "version": "authored-v2",
            "attribution": "Authored test fixture",
            "recipes": rows,
        },
    )
    original_embed = recipe_search.embeddings
    calls = []

    def fail(texts, query=False):
        calls.append(len(texts))
        if len(calls) == 2:
            raise Problem("TEST_OUTAGE", "Authored outage")
        return original_embed(texts, query)

    monkeypatch.setattr(recipe_search, "embeddings", fail)
    with pytest.raises(Problem, match="Authored outage"):
        ingest_recipes(path, sha)
    with connection() as c:
        assert (
            str(c.execute("SELECT catalog_id FROM active_recipe_catalog").fetchone()["catalog_id"])
            == original["catalog_id"]
        )
    monkeypatch.setattr(recipe_search, "embeddings", original_embed)
    resumed = ingest_recipes(path, sha)
    assert resumed["embedded"] == 3 and resumed["recipes"] == 35


def test_scaling_preserves_ambiguous_ingredients_and_is_not_doubled(tmp_path, actor):
    raw = source_recipe()
    raw["ingredients"] += [
        dict(id="salt", name={"en": "Salt"}, quantity=None, unit="toTaste", scaling="fixed"),
        dict(id="herbs", name={"en": "Herbs"}, quantity=1, unit="tbsp", scaling="damped"),
    ]
    *_, versions = import_fixture(tmp_path, [raw])
    plan = scale_recipe(actor, ref(versions))
    assert plan["ingredients"][0]["amount"] == "20"
    assert plan["ingredients"][0]["unit"] == "KG"
    assert len(plan["ingredients"]) == 5
    assert plan["ingredients"][3]["amount"] is None
    assert plan["ingredients"][4]["amount"] is None
    assert scale_recipe(actor, ref(versions)) == plan
    with pytest.raises(Problem) as error:
        scale_recipe(actor, ref(versions, portions=400))
    assert error.value.code == "RECIPE_PLAN_LOCKED"
    close_pools()
    assert get_plan(actor, PlanReference(plan_id=plan["recipe_plan_id"])) == plan


@pytest.fixture
def meal_products(monkeypatch, tmp_path):
    yield from installed_meal_products(monkeypatch, tmp_path, variable_weight=False)


@pytest.fixture
def variable_weight_meal_products(monkeypatch, tmp_path):
    yield from installed_meal_products(monkeypatch, tmp_path, variable_weight=True)


def installed_meal_products(monkeypatch, tmp_path, *, variable_weight):
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
            variable_weight=variable_weight,
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


def test_recipe_to_matched_products_to_backend_basket(tmp_path, actor, service, meal_products):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    pasta, eggs, pepper = plan["ingredients"]
    assert (
        pasta["amount"],
        pasta["conversion"]["sales_quantity"],
        pasta["conversion"]["excess"],
    ) == ("20", "7", "1")
    assert (eggs["amount"], eggs["conversion"]["sales_quantity"], eggs["conversion"]["excess"]) == (
        "100",
        "4",
        "20",
    )
    assert pepper["conversion"]["sales_quantity"] == "1"
    prepared = service.prepare_order(actor, request_for(plan))
    lines = {i["product_id"]: i for i in prepared["snapshot"]["lines"]}
    assert lines["recipe-egg"]["quantity"]["requested_unit"] == "piece"
    assert lines["recipe-egg"]["quantity"]["excess"] == "20"
    assert lines["recipe-spaghetti"]["quantity"]["sales_quantity"] == "7"
    assert prepared["order_id"] is None
    assert any(r["code"] == "OVERBUY_REQUIRES_APPROVAL" for r in prepared["reasons"])
    with pytest.raises(Problem) as error:
        match_ingredient(
            actor,
            MatchIngredient(
                plan_id=plan["recipe_plan_id"],
                revision=plan["recipe_plan_revision"],
                ingredient_id="spaghetti",
                product_id="recipe-spaghetti",
            ),
        )
    assert error.value.code == "RECIPE_PLAN_LOCKED"


def test_incomplete_wrong_product_stale_revision_and_catalog_changes(
    tmp_path, actor, service, meal_products
):
    *_, versions = import_fixture(tmp_path)
    plan = scale_recipe(actor, ref(versions))
    wrong = match_ingredient(
        actor,
        MatchIngredient(
            plan_id=plan["recipe_plan_id"],
            revision=1,
            ingredient_id="spaghetti",
            product_id="recipe-egg",
        ),
    )
    assert wrong["ingredients"][0]["status"] == "unresolved"
    with pytest.raises(Problem) as error:
        match_ingredient(
            actor,
            MatchIngredient(
                plan_id=plan["recipe_plan_id"],
                revision=1,
                ingredient_id="spaghetti",
                product_id="recipe-spaghetti",
            ),
        )
    assert error.value.code == "RECIPE_PLAN_CHANGED"
    plan = match_all(actor, wrong)
    bad = request_for(plan)
    bad.lines = bad.lines[:-1]
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, bad)
    assert error.value.code == "MEAL_BASKET_MISMATCH"
    with connection() as c:
        c.execute(
            "UPDATE products SET facts=jsonb_set(facts,'{name}','\"Changed product facts\"') WHERE id='recipe-spaghetti'"
        )
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, request_for(plan))
    assert error.value.code == "RECIPE_PRODUCT_CHANGED"
    with pytest.raises(Problem) as error:
        get_plan(actor | {"id": "other-agent"}, PlanReference(plan_id=plan["recipe_plan_id"]))
    assert error.value.code == "AUTHORITY_REVOKED"


def test_unreviewed_form_and_count_block_preparation(tmp_path, actor, service, meal_products):
    *_, versions = import_fixture(tmp_path, review=False)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    assert all(i["status"] == "unresolved" for i in plan["ingredients"])
    with connection() as c:
        c.execute(
            "UPDATE recipe_product_evidence SET piece_per_sales=NULL WHERE ingredient_id='egg'"
        )
    actor = actor | {"_turn_id": str(uuid4())}
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    assert plan["ingredients"][1]["status"] == "unresolved"
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, request_for(plan))
    assert error.value.code == "INCOMPLETE_MEAL_PLAN"


def test_tools_use_persisted_plan_and_cannot_publish_edited_totals(
    tmp_path, actor, service, meal_products, monkeypatch
):
    try:
        *_, versions = import_fixture(tmp_path)
        session = ToolSession(actor, service)
        assert {
            "search_recipes",
            "get_recipe",
            "scale_recipe",
            "get_recipe_plan",
            "match_ingredient",
        } <= session.registry.keys()

        def invoke(name, args):
            return session.invoke(name, json.dumps(args))

        found = invoke("search_recipes", {"query": "carbonara"})
        recipe = found["recipes"][0]
        invoke("get_recipe", {"recipe_id": recipe["recipe_id"], "version": recipe["version"]})
        plan = invoke("scale_recipe", dict(versions[0], portions=200))["meal_plan"]
        with pytest.raises(Problem) as error:
            invoke(
                "match_ingredient",
                dict(
                    plan_id=plan["recipe_plan_id"],
                    revision=plan["recipe_plan_revision"],
                    ingredient_id="spaghetti",
                    product_id="recipe-spaghetti",
                ),
            )
        assert error.value.code == "PRODUCT_NOT_VERIFIED"
        for item in list(plan["ingredients"]):
            invoke("get_product", {"product_id": "recipe-" + item["ingredient_id"]})
            plan = invoke(
                "match_ingredient",
                dict(
                    plan_id=plan["recipe_plan_id"],
                    revision=plan["recipe_plan_revision"],
                    ingredient_id=item["ingredient_id"],
                    product_id="recipe-" + item["ingredient_id"],
                ),
            )["meal_plan"]
        edited = deepcopy(plan)
        edited["ingredients"] = edited["ingredients"][:1]
        with pytest.raises(Problem) as error:
            invoke("publish_meal_plan", edited)
        assert error.value.code == "RECIPE_PLAN_REQUIRED"
        request = request_for(plan).model_dump(mode="json")
        request.pop("idempotency_key")
        for altered, code in [
            (request | {"recipe_plan_id": str(uuid4())}, "MEAL_BASKET_MISMATCH"),
            (request | {"recipe_plan_revision": 999}, "RECIPE_PLAN_CHANGED"),
        ]:
            with pytest.raises(Problem) as error:
                invoke("prepare_order", altered)
            assert error.value.code == code
        prepared = invoke("prepare_order", request)
        assert prepared["proposal_id"]
        for name, args in [
            ("scale_recipe", dict(versions[0], portions=200)),
            (
                "match_ingredient",
                dict(
                    plan_id=plan["recipe_plan_id"],
                    revision=plan["recipe_plan_revision"],
                    ingredient_id="spaghetti",
                    product_id="recipe-spaghetti",
                ),
            ),
        ]:
            with pytest.raises(Problem) as error:
                invoke(name, args)
            assert error.value.code == "MEAL_PLAN_LOCKED"
        # Reading after preparation is allowed and cannot replace the prepared plan.
        assert invoke("get_recipe_plan", {"plan_id": plan["recipe_plan_id"]})["meal_plan"] == plan
        other_actor = actor | {"_turn_id": str(uuid4())}
        other_plan = scale_recipe(other_actor, ref(versions, portions=100))
        assert (
            invoke("get_recipe_plan", {"plan_id": other_plan["recipe_plan_id"]})["meal_plan"]
            == other_plan
        )
        assert session.plan.model_dump(mode="json") == plan
        assert invoke("prepare_order", request)["proposal_id"] == prepared["proposal_id"]
        restarted = ToolSession(actor, service)
        assert (
            restarted.invoke("get_recipe_plan", json.dumps({"plan_id": plan["recipe_plan_id"]}))[
                "meal_plan"
            ]
            == plan
        )
    finally:
        settings.cache_clear()


def test_recipe_profile_uses_recipe_instruction_and_no_product_query_prefix(monkeypatch):
    from aimo import search_provider

    seen = []
    monkeypatch.setattr(
        search_provider,
        "embeddings",
        lambda texts, query=False: seen.append((texts, query)) or [[1.0] + [0.0] * 4095],
    )
    monkeypatch.setattr(settings(), "embedding_backend", "openrouter")
    recipe_search.embeddings(["vegetarian lunch"], query=True)
    assert "cooking recipes" in seen[0][0][0]
    assert "wholesale" not in seen[0][0][0] and seen[0][1] is False


def test_real_purchasing_confirmation_and_receipt_keep_recipe_reference(
    tmp_path, buyer, service, meal_products
):
    import os

    from fastapi.testclient import TestClient

    from aimo.api import create_app
    from aimo.auth import internal_agent
    from aimo.schemas import CommitRequest

    actor = internal_agent(buyer) | {"_turn_id": str(uuid4())}
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    request = request_for(plan)
    prepared = service.prepare_order(actor, request)
    commit = CommitRequest(
        proposal_id=prepared["proposal_id"],
        revision=prepared["revision"],
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(Problem) as error:
        service.commit_order(actor, commit)
    assert error.value.code == "CUSTOMER_CONFIRMATION_REQUIRED"
    with TestClient(create_app(service)) as client:
        signed = client.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"username": "buyer", "password": os.environ["DEMO_BUYER_PASSWORD"]},
        )
        assert signed.status_code == 200
        headers = {"Origin": "http://testserver", "X-CSRF-Token": signed.json()["csrf_token"]}
        confirmed = client.post(
            f"/api/purchases/{prepared['proposal_id']}/confirm",
            headers=headers,
            json=commit.model_dump(mode="json"),
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "accepted_mock"
        close_pools()
        repeated = client.post(
            f"/api/purchases/{prepared['proposal_id']}/confirm",
            headers=headers,
            json=commit.model_dump(mode="json"),
        )
        assert repeated.json() == confirmed.json()
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, request_for(plan))
    assert error.value.code == "RECIPE_PLAN_LOCKED"
    with connection() as c:
        saved = c.execute(
            "SELECT request FROM proposal_revisions WHERE proposal_id=%s",
            (prepared["proposal_id"],),
        ).fetchone()["request"]
        assert saved["recipe_plan_id"] == plan["recipe_plan_id"]
        assert saved["recipe_plan_revision"] == plan["recipe_plan_revision"]


def test_unknown_units_and_nonterminating_scaling_are_unresolved(tmp_path, actor):
    raw = source_recipe()
    raw["baseServings"] = 3
    raw["ingredients"][0]["quantity"] = 100
    raw["ingredients"][1]["unit"] = "slice"
    *_, versions = import_fixture(tmp_path, [raw])
    plan = scale_recipe(actor, ref(versions, portions=1))
    # MEA-012: 100 g at base 3 for one portion is 0.0333... kg and is rounded UP, never down.
    assert plan["ingredients"][0]["amount"] == "0.0334"
    assert plan["ingredients"][1]["amount"] is None


def test_empty_index_wrong_profile_and_revoked_identity(tmp_path, actor, monkeypatch):
    with pytest.raises(Problem) as error:
        search_recipes(actor, RecipeSearch(query="carbonara"))
    assert error.value.code == "RECIPES_NOT_READY"
    import_fixture(tmp_path)
    monkeypatch.setattr(recipe_search, "model_key", lambda: "different-recipe-profile")
    with pytest.raises(Problem) as error:
        search_recipes(actor, RecipeSearch(query="carbonara"))
    assert error.value.code == "RECIPE_MODEL_MISMATCH"
    with connection() as c:
        c.execute("UPDATE identities SET active=false WHERE id=%s", (actor["id"],))
    with pytest.raises(Problem) as error:
        scale_recipe(
            actor, ScaleRecipe(recipe_id="unitools:carbonara", version="missing", portions=200)
        )
    assert error.value.code == "AUTHORITY_REVOKED"


@pytest.mark.parametrize("outage", [False, True])
def test_hosted_recipe_search_reranks_only_its_shortlist(tmp_path, actor, monkeypatch, outage):
    from aimo import search_provider

    monkeypatch.setattr(settings(), "embedding_backend", "openrouter")
    monkeypatch.setattr(
        recipe_search,
        "embeddings",
        lambda texts, query=False: [[1.0] + [0.0] * 4095 for _ in texts],
    )
    *_, versions = import_fixture(
        tmp_path, [source_recipe("carbonara"), source_recipe("other-pasta")]
    )
    seen = []

    def rerank(query, documents):
        seen.append((query, documents))
        if outage:
            raise Problem("SEARCH_PROVIDER_UNAVAILABLE", "Authored reranker outage")
        return [(1, 0.9), (0, 0.1)]

    monkeypatch.setattr(search_provider, "rerank", rerank)
    result = search_recipes(actor, RecipeSearch(query="carbonara"))
    assert result["rerank_status"] == ("unavailable" if outage else "applied")
    assert len(result["recipes"]) == 2 and len(seen[0][1]) == 2
    assert seen[0][0].startswith("Find cooking recipes")


def test_batch_match_tool_matches_every_ingredient_in_one_revision(
    tmp_path, actor, service, meal_products
):
    """Issue 95 (MEA-014): the agent can match several ingredients with one tool call."""
    *_, versions = import_fixture(tmp_path)
    session = ToolSession(actor, service)
    assert "match_ingredients" in session.registry

    def invoke(name, args):
        return session.invoke(name, json.dumps(args))

    plan = invoke("scale_recipe", dict(versions[0], portions=200))["meal_plan"]
    pairs = [
        {"ingredient_id": i["ingredient_id"], "product_id": "recipe-" + i["ingredient_id"]}
        for i in plan["ingredients"]
    ]
    base = dict(plan_id=plan["recipe_plan_id"], revision=plan["recipe_plan_revision"])
    with pytest.raises(Problem) as error:  # no product was read with get_product yet
        invoke("match_ingredients", base | {"matches": pairs})
    assert error.value.code == "PRODUCT_NOT_VERIFIED"
    for pair in pairs:
        invoke("get_product", {"product_id": pair["product_id"]})
    matched = invoke("match_ingredients", base | {"matches": pairs})["meal_plan"]
    assert matched["recipe_plan_revision"] == plan["recipe_plan_revision"] + 1
    assert all(i["status"] == "matched" for i in matched["ingredients"])


def test_commit_rechecks_suitability_for_mass_ingredients(tmp_path, actor, service, meal_products):
    from aimo.schemas import CommitRequest

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    prepared = service.prepare_order(actor, request_for(plan))
    with connection() as c:
        c.execute("DELETE FROM recipe_product_evidence WHERE ingredient_id='spaghetti'")
    with pytest.raises(Problem) as error:
        service.commit_order(
            actor,
            CommitRequest(
                proposal_id=prepared["proposal_id"],
                revision=prepared["revision"],
                idempotency_key=str(uuid4()),
            ),
        )
    assert error.value.code == "RECIPE_PRODUCT_EVIDENCE_CHANGED"


def test_variable_weight_products_can_be_matched_and_only_warn(
    tmp_path, actor, service, variable_weight_meal_products
):
    """Issue 101 (BAS-007): a variable-weight product is flagged on the proposal, never a blocker."""
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    assert {i["status"] for i in plan["ingredients"]} == {"matched"}
    prepared = service.prepare_order(actor, request_for(plan))
    warnings = [r for r in prepared["reasons"] if r["code"] == "VARIABLE_WEIGHT_UNRESOLVED"]
    assert warnings and {r["severity"] for r in warnings} == {"warning"}
    assert prepared["policy_outcome"] != "needs_resolution"


def test_commit_after_a_planned_product_left_the_catalog_is_a_problem_not_a_crash(
    tmp_path, actor, service, meal_products
):
    """Issue 94: a product missing from the active catalog must not raise a bare KeyError."""
    from aimo.schemas import CommitRequest

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    prepared = service.prepare_order(actor, request_for(plan))
    with connection() as c:
        c.execute("DELETE FROM products WHERE id=%s", (plan["ingredients"][0]["product_id"],))
    with pytest.raises(Problem) as error:
        service.commit_order(
            actor,
            CommitRequest(
                proposal_id=prepared["proposal_id"],
                revision=prepared["revision"],
                idempotency_key=str(uuid4()),
            ),
        )
    assert error.value.code in {"RECIPE_PRODUCT_EVIDENCE_CHANGED", "RECIPE_PRODUCT_CHANGED"}


@pytest.mark.parametrize("pool_size", [1, 2])
def test_concurrent_preparations_release_connections_and_plan_locks_during_supplier_io(
    tmp_path, actor, service, meal_products, monkeypatch, pool_size
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    *_, versions = import_fixture(tmp_path)
    plans = [
        match_all(actor, scale_recipe(actor | {"_turn_id": str(uuid4())}, ref(versions)))
        for _ in range(2)
    ]
    monkeypatch.setattr(settings(), "db_pool_max_size", pool_size)
    monkeypatch.setattr(settings(), "db_pool_timeout_seconds", 1)
    barrier = Barrier(2)
    lookup = service.connector.lookup

    def supplier_lookup(*args):
        # Both callers have reached supplier I/O; neither can retain a checkout
        # or plan lock. This must also work with just one pool connection.
        leader = barrier.wait(timeout=5)
        if leader == 0:
            with connection() as c:
                c.execute("SELECT id FROM recipe_plans ORDER BY id FOR UPDATE NOWAIT").fetchall()
        barrier.wait(timeout=5)
        return lookup(*args)

    monkeypatch.setattr(service.connector, "lookup", supplier_lookup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda p: service.prepare_order(actor, request_for(p)), plans))
    assert len({r["proposal_id"] for r in results}) == 2
    with connection() as c:
        assert c.execute("SELECT bool_and(locked) AS locked FROM recipe_plans").fetchone()["locked"]


def test_one_recipe_plan_cannot_create_two_proposals_but_retry_returns_existing(
    tmp_path, actor, service, meal_products, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    requests = [request_for(plan), request_for(plan)]
    barrier = Barrier(2)
    lookup = service.connector.lookup

    def supplier_lookup(*args):
        barrier.wait(timeout=5)
        return lookup(*args)

    def prepare(request):
        try:
            return service.prepare_order(actor, request)
        except Problem as exc:
            return exc.code

    monkeypatch.setattr(service.connector, "lookup", supplier_lookup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(prepare, requests))
    winner = next(i for i, result in enumerate(results) if isinstance(result, dict))
    assert results[1 - winner] == "RECIPE_PLAN_LOCKED"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 1

    def no_supplier_call(*args):
        pytest.fail("A retry or locked plan must not perform supplier I/O")

    monkeypatch.setattr(service.connector, "lookup", no_supplier_call)
    close_pools()
    assert (
        service.prepare_order(actor, requests[winner])["proposal_id"]
        == results[winner]["proposal_id"]
    )
    later_actor = actor | {"_turn_id": str(uuid4())}
    get_plan(later_actor, PlanReference(plan_id=plan["recipe_plan_id"]))
    with pytest.raises(Problem) as error:
        service.prepare_order(later_actor, request_for(plan))
    assert error.value.code == "RECIPE_PLAN_LOCKED"


def test_recipe_preparation_rechecks_revision_after_supplier_io(
    tmp_path, actor, service, meal_products, monkeypatch
):
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    lookup = service.connector.lookup

    def supplier_lookup(*args):
        # An edit can commit while the supplier responds, so final persistence
        # must validate the plan again instead of saving the earlier snapshot.
        match_ingredient(
            actor,
            MatchIngredient(
                plan_id=plan["recipe_plan_id"],
                revision=plan["recipe_plan_revision"],
                ingredient_id="spaghetti",
                product_id="recipe-spaghetti",
            ),
        )
        return lookup(*args)

    monkeypatch.setattr(service.connector, "lookup", supplier_lookup)
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, request_for(plan))
    assert error.value.code == "RECIPE_PLAN_CHANGED"
    with connection() as c:
        assert not c.execute("SELECT locked FROM recipe_plans").fetchone()["locked"]
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0


def test_recipe_proposal_and_plan_lock_roll_back_together(
    tmp_path, actor, service, meal_products, monkeypatch
):
    from aimo import approval_workflow

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    request = request_for(plan)
    original_render = approval_workflow.render

    def fail_after_persistence(*args, **kwargs):
        raise RuntimeError("Authored failure before transaction commit")

    monkeypatch.setattr(approval_workflow, "render", fail_after_persistence)
    with pytest.raises(RuntimeError, match="Authored failure"):
        service.prepare_order(actor, request)
    with connection() as c:
        assert not c.execute("SELECT locked FROM recipe_plans").fetchone()["locked"]
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0
    monkeypatch.setattr(approval_workflow, "render", original_render)
    assert service.prepare_order(actor, request)["proposal_id"]


def test_recipe_tools_keep_direct_product_purchases_available(
    actor, service, request_data, monkeypatch
):
    session = ToolSession(actor, service)
    session.invoke("get_product", json.dumps({"product_id": "464306"}))
    session.invoke(
        "publish_meal_plan",
        json.dumps(
            {
                "title": "Order 10 L milk",
                "portions": 1,
                "ingredients": [
                    {"name": "Milk", "amount": "10", "unit": "L", "product_id": "464306"}
                ],
            }
        ),
    )
    request = {k: v for k, v in request_data.items() if k != "idempotency_key"}
    prepared = session.invoke("prepare_order", json.dumps(request))
    assert prepared["proposal_id"]
    assert prepared["request"]["recipe_plan_id"] is None
    assert prepared["request"]["lines"][0]["amount"] == "10"
    # Service remains additive for callers outside the chat tool harness too.
    assert service.prepare_order(actor, PrepareRequest(**request_data))["proposal_id"]


@pytest.mark.parametrize(
    "closed", ["expired", "needs_resolution", "delivery_date", "destination", "budget", "policy"]
)
def test_closed_recipe_proposal_refreshes_in_place_without_rematching(
    tmp_path, actor, service, meal_products, closed, monkeypatch, request_data
):
    from aimo import conversations
    from aimo.schemas import CommitRequest

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    original_request = request_for(plan)
    if closed == "delivery_date":
        original_request.delivery_date = date.today() - timedelta(days=1)
    elif closed in {"destination", "policy"}:
        original_request.destination = "mistyped-destination"
    elif closed == "budget":
        original_request.budget_gross = Decimal("0.01")
    elif closed == "expired":
        monkeypatch.setattr(settings(), "proposal_ttl_seconds", -1)
    elif closed == "needs_resolution":
        with connection() as c:
            c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    first = service.prepare_order(actor, original_request)
    assert first["recipe_basis"] == "saved_recipe"
    if closed in {"delivery_date", "destination", "budget", "policy"}:
        assert first["policy_outcome"] == "denied"
        # A past delivery also has expired supplier terms; keep freshness precedence.
        if closed == "delivery_date":
            assert first["approval_status"] == "expired"
        assert first["next_action"] == {
            "type": "request_fresh_proposal" if closed == "delivery_date" else "revise_request",
            "tool": "prepare_order",
        }
        assert (
            service.get_proposal(actor, first["proposal_id"])["next_action"] == first["next_action"]
        )
        expected_code = {
            "delivery_date": "DELIVERY_IN_PAST",
            "destination": "DESTINATION_NOT_ALLOWED",
            "policy": "DESTINATION_NOT_ALLOWED",
            "budget": "HARD_BUDGET_EXCEEDED",
        }[closed]
        assert any(r["code"] == expected_code for r in first["reasons"])
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", 900)
    if closed == "needs_resolution":
        assert first["policy_outcome"] == closed
    if closed == "needs_resolution":
        with connection() as c:
            c.execute("UPDATE identities SET active=true WHERE id='buyer'")

    if closed == "policy":
        with connection() as c:
            c.execute("SELECT id FROM buyers WHERE id='demo-hotel' FOR UPDATE")
            rules = c.execute(
                "SELECT rules FROM policies WHERE buyer_id='demo-hotel' AND version=1"
            ).fetchone()["rules"]
            rules["destinations"].append(original_request.destination)
            c.execute(
                "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',2,%s)",
                (js(rules),),
            )
            c.execute("UPDATE buyers SET current_policy=2 WHERE id='demo-hotel'")
    newer = service.prepare_order(actor, PrepareRequest(**request_data))
    before = conversations.purchases(actor, 0, 1)
    assert before["items"][0]["proposal_id"] == newer["proposal_id"]
    assert before["next_offset"] == 1
    with connection() as c:
        created_at = c.execute(
            "SELECT created_at FROM proposals WHERE id=%s", (first["proposal_id"],)
        ).fetchone()["created_at"]
    # Old preparation keys retain their retry meaning; new turns can refresh.
    assert service.prepare_order(actor, original_request)["revision"] == 1
    close_pools()
    later = actor | {"_turn_id": str(uuid4())}
    saved = get_plan(later, PlanReference(plan_id=plan["recipe_plan_id"]))
    assert saved == plan
    fresh_request = request_for(saved)
    if closed == "policy":
        fresh_request.destination = original_request.destination
    fresh = service.prepare_order(later, fresh_request)
    assert fresh["proposal_id"] == first["proposal_id"] and fresh["revision"] == 2
    assert fresh["recipe_basis"] == "saved_recipe"
    assert fresh["approval_status"] == "pending"
    assert fresh["approval_id"] != first["approval_id"]
    assert service.prepare_order(later, fresh_request)["revision"] == 2
    assert get_plan(later, PlanReference(plan_id=plan["recipe_plan_id"])) == plan
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 2
        assert (
            c.execute(
                "SELECT created_at FROM proposals WHERE id=%s", (first["proposal_id"],)
            ).fetchone()["created_at"]
            == created_at
        )
        assert (
            str(c.execute("SELECT proposal_id FROM recipe_plans").fetchone()["proposal_id"])
            == first["proposal_id"]
        )
    after = conversations.purchases(actor, 0, 1)
    assert after["items"][0]["proposal_id"] == first["proposal_id"]
    assert conversations.purchases(actor, 1, 1)["items"][0]["proposal_id"] == newer["proposal_id"]
    with pytest.raises(Problem) as error:
        service.commit_order(
            actor,
            CommitRequest(
                proposal_id=first["proposal_id"], revision=1, idempotency_key=str(uuid4())
            ),
        )
    assert error.value.code == "STALE_REVISION"


def test_denied_recipe_refresh_does_not_bypass_purchase_checks(
    tmp_path, actor, service, meal_products
):
    from aimo.schemas import CommitRequest

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    request = request_for(plan)
    request.budget_gross = Decimal("0.01")
    first = service.prepare_order(actor, request)
    later = actor | {"_turn_id": str(uuid4())}
    request.idempotency_key = str(uuid4())
    refreshed = service.prepare_order(later, request)
    assert refreshed["proposal_id"] == first["proposal_id"] and refreshed["revision"] == 2
    assert refreshed["policy_outcome"] == "denied"
    assert refreshed["approval_id"] is None
    assert refreshed["next_action"] == {"type": "revise_request", "tool": "prepare_order"}
    with pytest.raises(Problem) as error:
        service.commit_order(
            later,
            CommitRequest(
                proposal_id=first["proposal_id"], revision=2, idempotency_key=str(uuid4())
            ),
        )
    assert error.value.code == "COMMIT_BLOCKED"
    assert get_plan(later, PlanReference(plan_id=plan["recipe_plan_id"])) == plan
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM orders").fetchone()["n"] == 0


@pytest.mark.parametrize("expired", [False, True])
def test_stopped_recipe_basket_requires_new_plan(
    tmp_path, actor, buyer, service, meal_products, expired, monkeypatch
):
    from aimo import approval_workflow
    from aimo.schemas import DecisionRequest

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    request = request_for(plan)
    first = service.prepare_order(actor, request)
    approval_workflow.record_human_decision(
        buyer, first["approval_id"], DecisionRequest(revision=1, decision="reject")
    )
    if expired:
        future = approval_workflow.now() + timedelta(hours=1)
        monkeypatch.setattr(approval_workflow, "now", lambda: future)

    def unexpected_lookup(*args):
        pytest.fail("A stopped basket must be rejected before supplier I/O")

    monkeypatch.setattr(service.connector, "lookup", unexpected_lookup)
    assert service.prepare_order(actor, request)["next_action"]["type"] == "stop"
    later = actor | {"_turn_id": str(uuid4())}
    saved = get_plan(later, PlanReference(plan_id=plan["recipe_plan_id"]))
    with pytest.raises(Problem, match="new recipe plan") as error:
        service.prepare_order(later, request_for(saved))
    assert error.value.code == "RECIPE_PLAN_LOCKED"
    assert service.get_proposal(actor, first["proposal_id"])["next_action"]["type"] == "stop"
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposal_revisions").fetchone()["n"] == 1
    new_plan = scale_recipe(later, ref(versions))
    assert new_plan["recipe_plan_id"] != plan["recipe_plan_id"]


@pytest.mark.parametrize("still_blocked", [False, True])
def test_concurrent_recipe_refreshes_cannot_both_append_a_revision(
    tmp_path, actor, service, meal_products, monkeypatch, still_blocked
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", -1)
    service.prepare_order(actor, request_for(plan))
    monkeypatch.setattr(settings(), "proposal_ttl_seconds", 900)
    if still_blocked:
        with connection() as c:
            c.execute("UPDATE identities SET active=false WHERE id='buyer'")
    barrier = Barrier(2)
    lookup = service.connector.lookup

    def supplier_lookup(*args):
        barrier.wait(timeout=5)
        return lookup(*args)

    monkeypatch.setattr(service.connector, "lookup", supplier_lookup)

    def refresh(_):
        request = request_for(plan)
        try:
            return service.prepare_order(actor, request)
        except Problem as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(refresh, range(2)))
    success = [r for r in results if isinstance(r, dict)]
    assert len(success) == 1 and success[0]["revision"] == 2
    assert [r for r in results if isinstance(r, str)] == [
        "RECIPE_PROPOSAL_CHANGED" if still_blocked else "RECIPE_PLAN_LOCKED"
    ]
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM proposal_revisions").fetchone()["n"] == 2
        assert c.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 1


def test_new_turn_free_form_basket_is_labeled_without_recipe_completeness_claim(
    tmp_path, actor, service, meal_products, monkeypatch
):
    *_, versions = import_fixture(tmp_path, review=False)
    unresolved = scale_recipe(actor, ref(versions))
    assert all(i["status"] == "unresolved" for i in unresolved["ingredients"])
    later = ToolSession(actor | {"_turn_id": str(uuid4())}, service)
    later.invoke("get_product", json.dumps({"product_id": "recipe-spaghetti"}))
    later.invoke(
        "publish_meal_plan",
        json.dumps(
            {
                "title": unresolved["title"],
                "portions": 200,
                "ingredients": [
                    {
                        "name": "Spaghetti",
                        "amount": "20",
                        "unit": "KG",
                        "product_id": "recipe-spaghetti",
                    }
                ],
            }
        ),
    )
    request = {
        "request_id": "Free-form basket",
        "destination": "hotel-helsinki",
        "delivery_date": str(date.today() + timedelta(days=2)),
        "budget_gross": "1000",
        "lines": [{"product_id": "recipe-spaghetti", "amount": "20", "unit": "KG"}],
    }
    with pytest.raises(Problem) as error:
        later.invoke("prepare_order", json.dumps(request | {"recipe_basis": "saved_recipe"}))
    assert error.value.code == "INVALID_TOOL_ARGUMENTS"
    result = later.invoke("prepare_order", json.dumps(request))
    assert result["recipe_basis"] == "free_form" and result["request"]["recipe_plan_id"] is None


@pytest.mark.parametrize(
    "invalidate",
    [
        lambda data, reviews: data.update(license="CC0"),
        lambda data, reviews: data.pop("attribution"),
        lambda data, reviews: data.pop("version"),
        lambda data, reviews: data.update(recipes=[]),
        lambda data, reviews: data["recipes"].append(deepcopy(data["recipes"][0])),
        lambda data, reviews: data["recipes"][0]["ingredients"].append(
            deepcopy(data["recipes"][0]["ingredients"][0])
        ),
        lambda data, reviews: reviews["recipes"].update(unknown={"ingredients": {}}),
        lambda data, reviews: reviews["recipes"]["carbonara"]["ingredients"].update(
            unknown={"quantity": "1"}
        ),
        lambda data, reviews: reviews["recipes"]["carbonara"].update(unknown=True),
        lambda data, reviews: reviews["recipes"]["carbonara"]["ingredients"]["egg"].update(
            unknown=True
        ),
        lambda data, reviews: reviews.pop("source"),
        lambda data, reviews: reviews.update(unknown=True),
    ],
    ids=[
        "license",
        "attribution",
        "version",
        "empty",
        "duplicate-recipe",
        "duplicate-ingredient",
        "unknown-recipe",
        "unknown-ingredient",
        "recipe-field",
        "ingredient-field",
        "review-source",
        "review-field",
    ],
)
def test_malformed_recipe_import_never_pays_for_embeddings_or_replaces_corpus(
    tmp_path, actor, monkeypatch, invalidate
):
    path, _, review_path, original, _ = import_fixture(tmp_path)
    data, reviews = json.loads(path.read_text()), json.loads(review_path.read_text())
    invalidate(data, reviews)
    sha = write(path, data)
    write(review_path, reviews)

    def no_paid_work(*args, **kwargs):
        pytest.fail("Invalid source/review must be rejected before embedding")

    monkeypatch.setattr(recipe_search, "embeddings", no_paid_work)
    with pytest.raises(ValueError):
        ingest_recipes(path, sha, review_path)
    with connection() as c:
        assert (
            str(c.execute("SELECT catalog_id FROM active_recipe_catalog").fetchone()["catalog_id"])
            == original["catalog_id"]
        )


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[0.0] * 384], [[float("nan")] + [0.0] * 383]])
def test_invalid_recipe_embeddings_are_not_accepted(monkeypatch, vectors):
    monkeypatch.setattr(recipe_search.search, "embed", lambda *args, **kwargs: vectors)
    with pytest.raises(Problem) as error:
        recipe_search.embeddings(["meal request"])
    assert error.value.code == "RECIPE_EMBEDDING_INVALID"


def test_recipe_creation_requires_turn_known_version_and_supported_size(tmp_path, actor):
    *_, versions = import_fixture(tmp_path)
    with pytest.raises(Problem) as error:
        scale_recipe(actor | {"_turn_id": None}, ref(versions))
    assert error.value.code == "TURN_CONTEXT_REQUIRED"
    with pytest.raises(Problem) as error:
        get_recipe(actor, RecipeReference(recipe_id="unitools:carbonara", version="unknown"))
    assert error.value.code == "NOT_FOUND"
    with pytest.raises(Problem) as error:
        get_plan(actor, PlanReference(plan_id=uuid4()))
    assert error.value.code == "NOT_FOUND"
    raw = source_recipe()
    raw["ingredients"] = [raw["ingredients"][0] | {"id": f"ingredient-{i}"} for i in range(1001)]
    with pytest.raises(
        ValueError, match="at most 1000"
    ):  # MEA-013: the import refuses a larger recipe
        import_fixture(tmp_path, [raw])


def test_partial_recipe_reference_fails_closed(actor, service, request_data):
    with pytest.raises(Problem) as error:
        service.prepare_order(actor, PrepareRequest(**request_data, recipe_plan_revision=1))
    assert error.value.code == "RECIPE_PLAN_REQUIRED"
