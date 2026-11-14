"""MEA-008: refuse a free-form basket for a dish whose saved recipe plan is still unresolved.

"Same dish" means the same recipe title (Unicode NFKC, case-folded, whitespace collapsed) among
the buyer+agent's saved plans that are not locked, not tied to a proposal and still have an
ingredient that is not `matched`. Plans are scoped to the current conversation when the turn
belongs to one; a turn without a conversation record (direct service use) sees only plans
created in the last `WINDOW_HOURS`. A differently titled free-form plan is not detected.
"""

import unicodedata

from aimo.db import Problem, connection
from aimo.purchases import context

WINDOW_HOURS = 24


def normalise(title):
    return " ".join(unicodedata.normalize("NFKC", title).split()).casefold()


def unresolved_saved_plans_for_dish(identity, title):
    wanted = normalise(title)
    turn = str(identity.get("_turn_id") or "")
    with connection() as c:
        context(c, identity)
        conversation = c.execute(
            "SELECT conversation_id FROM conversation_turns WHERE id::text=%s", (turn,)
        ).fetchone()
        scope = (
            "AND rp.turn_id IN (SELECT id::text FROM conversation_turns WHERE conversation_id=%s)"
            if conversation
            else """AND (SELECT created_at FROM recipe_plan_revisions
            WHERE plan_id=rp.id AND revision=1) >= now() - make_interval(hours => %s)"""
        )
        rows = c.execute(
            f"""SELECT rp.id, rp.revision, rev.data FROM recipe_plans rp
            JOIN recipe_plan_revisions rev ON rev.plan_id=rp.id AND rev.revision=rp.revision
            WHERE rp.buyer_id=%s AND rp.agent_id=%s AND NOT rp.locked
            AND rp.proposal_id IS NULL {scope} ORDER BY rp.id""",
            (
                identity["buyer_id"],
                identity["id"],
                conversation["conversation_id"] if conversation else WINDOW_HOURS,
            ),
        ).fetchall()
    found = []
    for row in rows:
        data = row["data"]
        names = [i["name"] for i in data["ingredients"] if i.get("status") != "matched"]
        if names and normalise(data.get("title") or "") == wanted:
            found.append(
                {
                    "plan_id": str(row["id"]),
                    "revision": row["revision"],
                    "title": data["title"],
                    "unresolved": names,
                }
            )
    return found


def ensure_no_unresolved_saved_plan(identity, title):
    plans = unresolved_saved_plans_for_dish(identity, title)
    if plans:
        names = ", ".join(dict.fromkeys(n for plan in plans for n in plan["unresolved"]))
        raise Problem(
            "RECIPE_PLAN_UNRESOLVED",
            f"A saved recipe plan for this dish still has unresolved ingredients ({names}). "
            "Resolve them with match_ingredient or match_ingredients on that plan "
            "(get_recipe_plan shows it), or start a new customer message; "
            "do not prepare a free-form basket for the same dish.",
            422,
        )
