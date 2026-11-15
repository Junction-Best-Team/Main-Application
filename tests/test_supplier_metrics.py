"""Authored metric fixtures; no hosted database, supplier call or new embeddings."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from aimo import supplier_metrics
from aimo.agent_tools import ProductRequest, ToolSession
from aimo.config import settings
from aimo.db import connection
from aimo.guardrails import output_state, project
from aimo.permissions import configure_runtime_role
from aimo.request_brief import RequestBrief
from aimo.schemas import Requirements, SearchRequest
from aimo.search import get_product, search_products


@pytest.fixture
def metrics():
    old, active = "1" * 64, "2" * 64
    with connection() as c:
        previous = c.execute("SELECT * FROM active_supplier_datasets").fetchall()
        for dataset in supplier_metrics.DATASETS:
            for sha in (old, active):
                c.execute(
                    "INSERT INTO supplier_dataset_imports(dataset,sha256,source,row_count) VALUES(%s,%s,'authored test fixture',3)",
                    (dataset, sha),
                )
            c.execute(
                "INSERT INTO active_supplier_datasets(dataset,sha256) VALUES(%s,%s) ON CONFLICT(dataset) DO UPDATE SET sha256=excluded.sha256",
                (dataset, active),
            )
        values = [
            ("carbon_footprint", old, "464306", "99"),
            ("carbon_footprint", active, "464306", "0"),
            ("carbon_footprint", active, "464398", "2.4"),
            ("delivery_reliability", old, "464306", "0.1"),
            ("delivery_reliability", active, "464306", "0.92"),
            ("delivery_reliability", active, "464398", "0.98"),
        ]
        c.cursor().executemany(
            "INSERT INTO supplier_dataset_values(dataset,sha256,product_id,value) VALUES(%s,%s,%s,%s)",
            values,
        )
    yield active
    with connection() as c:
        c.execute("DELETE FROM active_supplier_datasets")
        for row in previous:
            c.execute(
                "INSERT INTO active_supplier_datasets(dataset,sha256) VALUES(%s,%s)",
                (row["dataset"], row["sha256"]),
            )
        for table in ("supplier_dataset_values", "supplier_dataset_imports"):
            c.execute(
                sql.SQL("DELETE FROM {} WHERE sha256=ANY(%s)").format(sql.Identifier(table)),
                ([old, active],),
            )


def test_product_tool_reads_only_active_dataset_hashes_and_retains_real_zero(
    agent, service, metrics
):
    session = ToolSession(agent | {"_turn_id": str(uuid4())}, service)
    product = session.product(ProductRequest(product_id="464306"))
    facts = product["supplier_metrics"]
    assert facts["carbon_footprint"]["value"] == "0"
    assert facts["delivery_reliability"]["value"] == "0.92"
    assert all(value["dataset_sha256"] == metrics for value in facts.values())
    assert facts["carbon_footprint"]["unit"] == "kg CO2-eq/kg"
    assert facts["carbon_footprint"]["basis"] == "estimated_product_group_average"
    assert project("get_product", product)["supplier_metrics"] == facts
    assert output_state("", session, [])["trusted_records"]["supplier_metrics"]["464306"] == facts


def test_missing_metric_is_unknown_not_zero(agent, metrics):
    product = get_product(agent, "463380")
    assert product["supplier_metrics"]["carbon_footprint"]["value"] is None
    assert product["supplier_metrics"]["delivery_reliability"]["value"] is None
    assert product["supplier_metrics"]["delivery_reliability"]["dataset_sha256"] == metrics


def test_adopting_existing_tables_preserves_imports_and_active_versions(agent, metrics):
    with connection() as c:
        before = c.execute(
            "SELECT * FROM supplier_dataset_imports ORDER BY dataset,sha256"
        ).fetchall()
        c.execute(
            (
                Path(__file__).resolve().parents[1] / "migrations/027_supplier_metrics.sql"
            ).read_text()
        )
        assert (
            before
            == c.execute(
                "SELECT * FROM supplier_dataset_imports ORDER BY dataset,sha256"
            ).fetchall()
        )
        c.execute(
            "UPDATE active_supplier_datasets SET sha256=%s WHERE dataset='carbon_footprint'",
            ("1" * 64,),
        )
    assert get_product(agent, "464306")["supplier_metrics"]["carbon_footprint"]["value"] == "99"


@pytest.mark.parametrize("strategy", ["keyword", "semantic", "hybrid"])
def test_search_sorts_relevant_candidates_without_dropping_dietary_filters(
    agent, metrics, strategy
):
    for preference, expected in [
        ("lower_carbon", "464306"),
        ("higher_delivery_reliability", "464398"),
    ]:
        result = search_products(
            agent, SearchRequest(query="milk", limit=20, sort_by=preference), strategy
        )
        assert result["products"][0]["id"] == expected
        assert result["sort_by"] == preference
        assert "shortlist" in result["note"]
    filtered = search_products(
        agent,
        SearchRequest(
            query="milk",
            sort_by="higher_delivery_reliability",
            requirements=Requirements(lactose_free=True),
        ),
        strategy,
    )
    assert all("FREE_FROM_LACTOSE" in p["claims"] for p in filtered["products"])


def test_unknown_and_invalid_values_never_win_a_comparison(metrics):
    with connection() as c:
        c.execute(
            "INSERT INTO supplier_dataset_values VALUES('delivery_reliability',%s,'invalid',1.1)",
            (metrics,),
        )
        c.execute(
            "INSERT INTO supplier_dataset_values VALUES('carbon_footprint',%s,'invalid','NaN')",
            (metrics,),
        )
        facts = supplier_metrics.load(c, ["missing", "invalid", "464306", "464398"])
    assert facts["invalid"]["carbon_footprint"]["value"] is None
    assert facts["invalid"]["delivery_reliability"]["value"] is None
    assert supplier_metrics.prefer(list(facts), facts, "lower_carbon") == [
        "464306",
        "464398",
        "missing",
        "invalid",
    ]


def test_metric_data_is_read_only_to_runtime():
    role = "supplier_metrics_test_" + uuid4().hex
    with psycopg.connect(settings().database_url) as c:
        if not c.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]:
            pytest.skip("Restricted-role test requires CREATEROLE")
        try:
            c.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            configure_runtime_role(c, role)
            c.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            for table in (
                "supplier_dataset_imports",
                "supplier_dataset_values",
                "active_supplier_datasets",
            ):
                c.execute(sql.SQL("SELECT * FROM {} LIMIT 1").format(sql.Identifier(table)))
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    assert not c.execute(
                        "SELECT has_table_privilege(current_user,%s,%s)", (table, privilege)
                    ).fetchone()[0]
        finally:
            c.rollback()


def test_persisted_preference_reaches_search_and_output_review(agent, service, metrics):
    session = ToolSession(agent | {"_turn_id": str(uuid4())}, service)
    session.brief = RequestBrief(
        intent="explore",
        goal="Compare milk",
        starting_point="products",
        product_preferences=["higher_delivery_reliability"],
    )
    result = session.search(SearchRequest(query="milk", limit=20))
    assert result["sort_by"] == "higher_delivery_reliability"
    assert result["products"][0]["id"] == "464398"
    evidence = output_state("", session, [])["trusted_records"]["supplier_metrics"]
    assert set(evidence) == {p["id"] for p in result["products"]}
    assert evidence["464398"]["delivery_reliability"]["value"] == "0.98"


def test_no_active_imports_yield_explicit_unknowns():
    # Always roll back: other fixtures may already have active versions.
    with connection() as c, c.transaction(force_rollback=True):
        c.execute("DELETE FROM active_supplier_datasets")
        facts = supplier_metrics.load(c, ["464306"])["464306"]
        assert all(v["value"] is None and v["dataset_sha256"] is None for v in facts.values())
        assert Decimal("0") != facts["carbon_footprint"]["value"]
