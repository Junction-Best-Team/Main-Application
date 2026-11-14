"""Recipe import/planning against PostgreSQL; authored recipe/catalog/commerce fixtures."""

import hashlib
import json
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from aimo import fixtures, recipe_search
from aimo.agent_tools import ToolSession
from aimo.config import settings
from aimo.db import Problem, close_pools, connection, fingerprint
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
    monkeypatch.setattr(settings(), "recipe_planning_enabled", True)
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
        prepared = invoke("prepare_order", request)
        assert prepared["proposal_id"]
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
    import sys

    seen = []
    provider = SimpleNamespace(
        embeddings=lambda texts, query=False: seen.append((texts, query)) or [[1.0] + [0.0] * 4095]
    )
    monkeypatch.setitem(sys.modules, "aimo.search_provider", provider)
    monkeypatch.setattr(recipe_search, "hosted", lambda: True)
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
    assert plan["ingredients"][0]["amount"] is None
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
    import sys

    monkeypatch.setattr(recipe_search, "hosted", lambda: True)
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

    monkeypatch.setitem(sys.modules, "aimo.search_provider", SimpleNamespace(rerank=rerank))
    monkeypatch.setattr(
        "aimo.config.settings",
        lambda: SimpleNamespace(rerank_enabled=True, rerank_candidates=30),
    )
    result = search_recipes(actor, RecipeSearch(query="carbonara"))
    assert result["rerank_status"] == ("unavailable" if outage else "applied")
    assert len(result["recipes"]) == 2 and len(seen[0][1]) == 2
    assert seen[0][0].startswith("Find cooking recipes")


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
