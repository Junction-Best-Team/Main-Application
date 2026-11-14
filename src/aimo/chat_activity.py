"""Sanitized, best-effort tool activity fenced to the current worker attempt."""

from aimo.chat_schemas import ChatActivityEvent
from aimo.db import connection, js, now

# Product copy is server-owned. No provider-supplied names, arguments, results or errors.
TOOL_LABELS = {
    "search_recipes": "Searching recipes",
    "get_recipe": "Checking a recipe",
    "scale_recipe": "Scaling recipe portions",
    "get_recipe_plan": "Checking the saved recipe plan",
    "match_ingredient": "Matching an ingredient to products",
    "match_ingredients": "Matching ingredients to products",
    "search_products": "Searching products",
    "get_product": "Checking a product",
    "list_substitution_candidates": "Checking alternatives",
    "check_price_and_availability": "Checking prices and availability",
    "get_purchase_policy": "Checking purchasing rules",
    "publish_meal_plan": "Putting the meal plan together",
    "prepare_order": "Preparing the basket",
    "get_proposal": "Checking the saved basket",
    "get_order": "Checking the mock order receipt",
    "generate_recipe_image": "Creating a recipe illustration",
    "search_memory": "Checking saved preferences",
    "manage_memory": "Updating saved preferences",
}


def record_progress(turn, progress):
    """Append only ordered events from a live attempt; stale callbacks cannot publish.

    The agent's Progress observer catches storage failures so display metadata cannot
    change purchasing outcomes. 600 covers 24 rounds * 12 tools * 2 events, plus lifecycle.
    """
    if str(progress.turn_id) != str(turn["id"]):
        return
    label = {
        "started": "Checking your request",
        "complete": "Finishing the response",
        "error": "Response interrupted",
    }.get(progress.kind, TOOL_LABELS.get(progress.tool, "Using a tool"))
    item = ChatActivityEvent(sequence=progress.sequence, kind=progress.kind, label=label)
    update_draft = progress.draft_updated and (
        progress.draft is None or progress.draft.turn_id == str(turn["id"])
    )
    with connection() as c:
        c.execute(
            """UPDATE conversation_turns SET progress=progress || %s::jsonb,
            draft_cart=CASE WHEN %s THEN %s::jsonb ELSE draft_cart END
            WHERE id=%s AND attempt=%s AND state='running' AND lease_until>%s
            AND jsonb_array_length(progress)<600
            AND COALESCE((progress->-1->>'sequence')::int,0)<%s""",
            (js([item.model_dump()]), update_draft,
             js(progress.draft.model_dump(mode="json")) if progress.draft else None,
             turn["id"], turn["attempt"], now(), item.sequence),
        )
