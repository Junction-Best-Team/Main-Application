"""Sanitized, best-effort tool activity fenced to the current worker attempt."""

from aimo.chat_schemas import ChatActivityEvent
from aimo.db import connection, js, now

# Product copy is server-owned. No provider-supplied names, arguments or errors; completed
# tools may add a short detail built from their validated server result (tool_detail).
TOOL_LABELS = {
    "search_recipes": "Searching recipes",
    "get_recipe": "Checking a recipe",
    "scale_recipe": "Scaling recipe portions",
    "draft_recipe": "Calculating recipe quantities",
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


DETAIL_LIMIT = 160
OUTCOMES = {
    "ready_to_commit": "ready for your confirmation",
    "approval_required": "needs approval",
    "denied": "blocked by purchasing rules",
    "needs_resolution": "needs changes",
}


def _names(items, key, limit=3):
    names = [str(i.get(key) or "").strip() for i in items if isinstance(i, dict)]
    names = [n for n in names if n]
    shown = ", ".join(names[:limit])
    return shown + (f" +{len(names) - limit} more" if len(names) > limit else "")


def _count(n, word, plural=None):
    return f"{n} {word if n == 1 else plural or word + 's'}"


def _plan(plan):
    # Meal-plan titles and ingredient names can be model-authored and are only shown after
    # the output review (draft cart), so the activity line keeps to server-checked counts.
    ingredients = plan.get("ingredients") or []
    matched = sum(1 for i in ingredients if i.get("status") == "matched")
    unresolved = sum(1 for i in ingredients if i.get("status") == "unresolved")
    parts = [_count(plan.get("portions") or 0, "portion"), _count(len(ingredients), "ingredient")]
    if matched:
        parts.append(f"{matched} matched to products")
    if unresolved:
        parts.append(f"{unresolved} unresolved")
    return " · ".join(parts)


def _detail(tool, out):
    if tool == "search_recipes":
        recipes = out.get("recipes") or []
        if not recipes:
            return "No matching recipes"
        return f"Found {_count(len(recipes), 'recipe')}: {_names(recipes, 'title')}"
    if tool == "get_recipe":
        recipe = out.get("recipe") or {}
        if not recipe.get("title"):
            return None
        return (f"{recipe.get('title')} · serves {recipe.get('base_servings')} · "
                f"{_count(len(recipe.get('ingredients') or []), 'ingredient')}")
    if tool in ("scale_recipe", "draft_recipe", "get_recipe_plan", "match_ingredient",
                "match_ingredients", "publish_meal_plan"):
        return _plan(out.get("meal_plan") or {})
    if tool == "search_products":
        products = out.get("products") or []
        if not products:
            return "No matching products"
        return f"Found {_count(len(products), 'product')}: {_names(products, 'name')}"
    if tool == "get_product":
        return out.get("name")
    if tool == "list_substitution_candidates":
        return _count(len(out.get("candidates") or []), "alternative")
    if tool == "check_price_and_availability":
        evidence = [e for e in (out.get("products") or {}).values() if isinstance(e, dict)]
        priced = sum(1 for e in evidence if e.get("gross"))
        stocked = 0
        for e in evidence:
            try:
                stocked += float(e.get("available_sales_quantity") or 0) > 0
            except ValueError:
                pass
        # Fixture evidence must never read as live supplier data.
        source = "live supplier data" if out.get("mode") == "live" else "demo fixture data"
        return (f"{_count(len(evidence), 'product')} · {priced} priced · "
                f"{stocked} in stock · {source}")
    if tool == "get_purchase_policy":
        version = out.get("policy_version")
        return f"Purchasing rules version {version}" if version else None
    if tool in ("prepare_order", "get_proposal"):
        snapshot = out.get("snapshot") or {}
        parts = [_count(len(snapshot.get("lines") or []), "line")]
        if snapshot.get("gross_total") and snapshot.get("currency"):
            parts.append(f"{snapshot['gross_total']} {snapshot['currency']}")
        outcome = OUTCOMES.get(out.get("policy_outcome"))
        if outcome:
            parts.append(outcome)
        return "Mock basket · " + " · ".join(parts)
    if tool == "get_order":
        return "Mock order receipt · accepted (mock)"
    if tool == "search_memory":
        return _count(len(out.get("items") or []), "saved preference")
    if tool == "manage_memory":
        return "Saved preferences updated"
    if tool == "generate_recipe_image":
        return "Illustration ready"
    return None


def tool_detail(tool, output):
    """A short display line built only from a tool's validated server result.

    Never the model's arguments or prose, provider errors or private reasoning. Best effort:
    an unexpected shape yields no detail rather than failing the turn.
    """
    try:
        out = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        if not isinstance(out, dict):
            return None
        text = " ".join(str(_detail(tool, out) or "").split())
    except Exception:
        return None
    if not text:
        return None
    return text if len(text) <= DETAIL_LIMIT else text[:DETAIL_LIMIT - 1].rstrip() + "…"


def record_progress(turn, progress):
    """Append only ordered events from a live attempt; stale callbacks cannot publish.

    The agent's Progress observer catches storage failures so display metadata cannot
    change purchasing outcomes. 640 covers 24 rounds * (12 tools * 2 events + thinking),
    plus lifecycle.
    """
    if str(progress.turn_id) != str(turn["id"]):
        return
    later_round = (getattr(progress, "round_number", None) or 1) > 1
    label = {
        "started": "Checking your request",
        # After tool calls the model reads their results before choosing the next step.
        "thinking": "Reading the results" if later_round else "Thinking",
        "reviewing": "Reviewing the reply",
        "complete": "Finishing the response",
        "error": "Response interrupted",
    }.get(progress.kind, TOOL_LABELS.get(progress.tool, "Using a tool"))
    detail = getattr(progress, "detail", None) if progress.kind == "tool_completed" else None
    item = ChatActivityEvent(
        sequence=progress.sequence, kind=progress.kind, label=label, detail=detail
    )
    update_draft = progress.draft_updated and (
        progress.draft is None or progress.draft.turn_id == str(turn["id"])
    )
    with connection() as c:
        c.execute(
            """UPDATE conversation_turns SET progress=progress || %s::jsonb,
            draft_cart=CASE WHEN %s THEN %s::jsonb ELSE draft_cart END
            WHERE id=%s AND attempt=%s AND state='running' AND lease_until>%s
            AND jsonb_array_length(progress)<640
            AND COALESCE((progress->-1->>'sequence')::int,0)<%s""",
            (js([item.model_dump(exclude_none=True)]), update_draft,
             js(progress.draft.model_dump(mode="json")) if progress.draft else None,
             turn["id"], turn["attempt"], now(), item.sequence),
        )
