"""MEA-008: a free-form basket for a dish whose saved recipe plan is unresolved is refused.

Authored rows only: plans are inserted directly (same columns `recipes.scale_recipe` writes), so
no catalog, embedding or supplier call is involved.
"""

from uuid import uuid4

import pytest

from aimo.db import Problem, connection, js
from aimo.recipe_guard import ensure_no_unresolved_saved_plan, unresolved_saved_plans_for_dish


@pytest.fixture(autouse=True)
def clean_recipes():
    with connection() as c:
        # A recipe reset cascades into guarded history (PER-002): say it is deliberate.
        c.execute("SET LOCAL aimo.allow_history_truncate = 'on'")
        c.execute("TRUNCATE recipes CASCADE")
    yield


@pytest.fixture
def actor(agent):
    return agent | {"_turn_id": str(uuid4())}


def add_recipe():
    with connection() as c:
        c.execute("INSERT INTO recipes VALUES('guard-recipe') ON CONFLICT DO NOTHING")
        c.execute(
            """INSERT INTO recipe_versions(recipe_id,version,data,source,source_version,source_hash,
            attribution,license) VALUES('guard-recipe','1','{}','authored','1','x','authored','test')
            ON CONFLICT DO NOTHING"""
        )


def add_plan(identity, title, statuses, turn_id=None, locked=False, age_hours=0):
    """Insert a saved plan the way scale_recipe stores it; `statuses` is name -> status."""
    add_recipe()
    pid = uuid4()
    ingredients = [
        {"ingredient_id": f"i{n}", "name": name, "status": status}
        for n, (name, status) in enumerate(statuses.items())
    ]
    with connection() as c:
        c.execute(
            """INSERT INTO recipe_plans(id,buyer_id,agent_id,turn_id,recipe_id,recipe_version,
            portions,locked) VALUES(%s,%s,%s,%s,'guard-recipe','1',200,%s)""",
            (pid, identity["buyer_id"], identity["id"], turn_id or str(uuid4()), locked),
        )
        c.execute(
            "INSERT INTO recipe_plan_revisions VALUES(%s,1,%s,now() - make_interval(hours => %s))",
            (pid, js({"title": title, "ingredients": ingredients}), age_hours),
        )
    return pid


UNRESOLVED = {"Spaghetti": "unresolved", "Eggs": "matched", "Black pepper": "unresolved"}


def test_same_title_with_unresolved_ingredients_is_refused_naming_them(actor):
    pid = add_plan(actor, "Spaghetti Carbonara", UNRESOLVED)
    found = unresolved_saved_plans_for_dish(actor, "Spaghetti Carbonara")
    assert found == [
        {
            "plan_id": str(pid),
            "revision": 1,
            "title": "Spaghetti Carbonara",
            "unresolved": ["Spaghetti", "Black pepper"],
        }
    ]
    with pytest.raises(Problem) as error:
        ensure_no_unresolved_saved_plan(actor, "Spaghetti Carbonara")
    assert error.value.code == "RECIPE_PLAN_UNRESOLVED" and error.value.status == 422
    message = str(error.value.message)
    assert "Spaghetti" in message and "Black pepper" in message and "Eggs" not in message
    assert "match_ingredient" in message and "new customer message" in message


def test_title_comparison_ignores_case_and_whitespace(actor):
    add_plan(actor, "  Spaghetti   Carbonara ", UNRESOLVED)
    assert unresolved_saved_plans_for_dish(actor, "spaghetti carbonara")
    with pytest.raises(Problem):
        ensure_no_unresolved_saved_plan(actor, "SPAGHETTI\tCARBONARA")


def test_a_plan_with_every_ingredient_matched_does_not_block(actor):
    add_plan(actor, "Spaghetti Carbonara", {"Spaghetti": "matched", "Eggs": "matched"})
    assert unresolved_saved_plans_for_dish(actor, "Spaghetti Carbonara") == []
    assert ensure_no_unresolved_saved_plan(actor, "Spaghetti Carbonara") is None


def test_a_proposed_status_also_counts_as_not_matched(actor):
    add_plan(actor, "Spaghetti Carbonara", {"Spaghetti": "matched", "Eggs": "proposed"})
    assert unresolved_saved_plans_for_dish(actor, "Spaghetti Carbonara")[0]["unresolved"] == [
        "Eggs"
    ]


def test_a_different_title_is_allowed(actor):
    add_plan(actor, "Spaghetti Carbonara", UNRESOLVED)
    assert ensure_no_unresolved_saved_plan(actor, "Lasagne") is None


def test_another_agent_or_buyer_plan_is_not_visible(actor):
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('other-hotel','456',1)")
        c.execute(
            """INSERT INTO identities VALUES('other-agent','other-hotel','agent',true,'!x',
            '{"currency":"EUR","autonomous_limit":"0"}')"""
        )
        c.execute(
            """INSERT INTO identities VALUES('second-agent',%s,'agent',true,'!x',
            '{"currency":"EUR","autonomous_limit":"0"}')""",
            (actor["buyer_id"],),
        )
    add_plan({"buyer_id": "other-hotel", "id": "other-agent"}, "Spaghetti Carbonara", UNRESOLVED)
    add_plan(
        {"buyer_id": actor["buyer_id"], "id": "second-agent"}, "Spaghetti Carbonara", UNRESOLVED
    )
    assert unresolved_saved_plans_for_dish(actor, "Spaghetti Carbonara") == []
    assert ensure_no_unresolved_saved_plan(actor, "Spaghetti Carbonara") is None


def test_a_locked_prepared_plan_is_not_counted(actor):
    add_plan(actor, "Spaghetti Carbonara", UNRESOLVED, locked=True)
    assert unresolved_saved_plans_for_dish(actor, "Spaghetti Carbonara") == []


def test_without_a_conversation_only_recent_plans_count(actor):
    add_plan(actor, "Spaghetti Carbonara", UNRESOLVED, age_hours=25)
    assert unresolved_saved_plans_for_dish(actor, "Spaghetti Carbonara") == []
    add_plan(actor, "Spaghetti Carbonara", UNRESOLVED, age_hours=1)
    assert len(unresolved_saved_plans_for_dish(actor, "Spaghetti Carbonara")) == 1


def add_conversation_turn(actor, conversation_id=None):
    """Persist a turn (and its conversation if new); returns (conversation_id, turn_id)."""
    conversation_id = conversation_id or uuid4()
    turn_id = uuid4()
    with connection() as c:
        c.execute(
            """INSERT INTO conversations(id,buyer_id,title,create_key,create_hash)
            VALUES(%s,%s,'t',%s,'h') ON CONFLICT DO NOTHING""",
            (conversation_id, actor["buyer_id"], str(conversation_id)),
        )
        c.execute(
            """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,
            lease_until,attempt) VALUES(%s,%s,%s,'h','complete',now(),%s)""",
            (turn_id, conversation_id, str(turn_id), uuid4()),
        )
    return conversation_id, turn_id


def test_inside_a_conversation_only_that_conversations_plans_count(actor):
    first, earlier_turn = add_conversation_turn(actor)
    _, later_turn = add_conversation_turn(actor, first)
    _, other_turn = add_conversation_turn(actor)
    add_plan(actor, "Spaghetti Carbonara", UNRESOLVED, turn_id=str(earlier_turn))
    add_plan(actor, "Spaghetti Carbonara", UNRESOLVED, turn_id=str(other_turn), age_hours=0)
    same = actor | {"_turn_id": str(later_turn)}
    found = unresolved_saved_plans_for_dish(same, "Spaghetti Carbonara")
    assert len(found) == 1
    # A plan from an old turn of the same conversation counts however old it is.
    old_turn = add_conversation_turn(actor, first)[1]
    add_plan(actor, "Old dish", UNRESOLVED, turn_id=str(old_turn), age_hours=400)
    assert len(unresolved_saved_plans_for_dish(same, "Old dish")) == 1
    # The other conversation does not see the first conversation's plan.
    elsewhere = actor | {"_turn_id": str(add_conversation_turn(actor)[1])}
    assert unresolved_saved_plans_for_dish(elsewhere, "Old dish") == []


def test_service_method_refuses_an_unresolved_saved_plan(actor, service):
    add_plan(actor, "Spaghetti Carbonara", UNRESOLVED)
    with pytest.raises(Problem) as error:
        service.ensure_saved_plan_resolved(actor, "Spaghetti Carbonara")
    assert error.value.code == "RECIPE_PLAN_UNRESOLVED"
    assert service.ensure_saved_plan_resolved(actor, "Lasagne") is None
