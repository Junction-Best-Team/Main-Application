"""Shared response and execution limits; reads never confer purchasing authority."""

# Only local, read-only tools qualify for larger batches.
PARALLEL_READS = frozenset(
    {"search_products", "get_product", "get_purchase_policy", "search_recipes", "get_recipe"}
)
MAX_TOOL_CALLS_PER_REPLY = 100
MAX_OTHER_CALLS_PER_REPLY = 12
# Keep tool/stage events below the existing 600-event API bound.
MAX_TOOL_CALLS_PER_TURN = 256
