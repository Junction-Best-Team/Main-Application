"""CNF-021 with a saved recipe plan: purging its unfinished proposal unlocks the plan.

A recipe-backed proposal links its plan (recipe_plans.proposal_id) and locks it. When the
unfinished proposal is purged the link is cleared and the plan is unlocked, so the same plan can be
prepared again as a new proposal instead of staying stuck behind RECIPE_PLAN_LOCKED. Authored
recipe fixtures and invented prices only.
"""

from datetime import timedelta
from uuid import uuid4

# Reuse the recipe test helpers and fixtures (authored fixtures, no live supplier).
from test_recipes import (  # noqa: F401  (fixtures are used by name)
    clean_recipes,
    import_fixture,
    match_all,
    meal_products,
    ref,
    request_for,
)

from aimo import approval_workflow as workflow
from aimo import auth
from aimo.db import connection, now
from aimo.recipes import scale_recipe


def test_a_purged_recipe_proposal_leaves_the_plan_reusable(request, tmp_path, buyer, service):
    request.getfixturevalue("meal_products")
    actor = auth.internal_agent(buyer) | {"_turn_id": str(uuid4())}
    *_, versions = import_fixture(tmp_path)
    plan = match_all(actor, scale_recipe(actor, ref(versions)))
    first = service.prepare_order(actor, request_for(plan))
    with connection() as c:
        row = c.execute("SELECT proposal_id, locked FROM recipe_plans").fetchone()
    assert str(row["proposal_id"]) == first["proposal_id"] and row["locked"] is True

    result = workflow.purge_unfinished_proposals(
        timedelta(days=30), as_of=now() + timedelta(days=31)
    )
    assert result["proposals"] == 1 and result["recipe_plans_unlinked"] == 1
    with connection() as c:
        row = c.execute("SELECT proposal_id, locked FROM recipe_plans").fetchone()
        revisions = c.execute("SELECT count(*) AS n FROM recipe_plan_revisions").fetchone()["n"]
    assert row["proposal_id"] is None and row["locked"] is False and revisions >= 1

    later = actor | {"_turn_id": str(uuid4())}
    again = service.prepare_order(later, request_for(plan))
    assert again["proposal_id"] != first["proposal_id"] and again["revision"] == 1
