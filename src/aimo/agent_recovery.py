"""Deterministic stopping/recovery copy; no inferred recipe evidence or authority."""

EVIDENCE_BLOCKERS = {
    "No current reviewed evidence that this product fits the ingredient and form.",
    "Verified ingredient count per sales unit is missing.",
    "Structured product data cannot convert the ingredient quantity into sales units.",
}


def recipe_blocked(plan):
    """Catalog searches cannot supply missing recipe facts or reviewed evidence.

    Missing/withdrawn products alone remain searchable. Unrecognised reasons do not
    stop discovery. A partial plan keeps every ingredient and its precise reason.
    """
    if not plan or not plan.recipe_plan_id:
        return False
    return any(
        item.status == "unresolved"
        and (item.amount is None or item.form == "unspecified" or item.reason in EVIDENCE_BLOCKERS)
        for item in plan.ingredients
    )


BLOCKED_NOTICE = (
    "The recipe needs reviewed ingredient details or product suitability/conversion evidence "
    "before matching can continue. More product searches cannot resolve that missing evidence. "
    "Review the unresolved items in the saved plan; no purchase was authorized."
)


def partial_notice(plan, code):
    cause = (
        "I reached the time limit." if code == "LLM_TIMEOUT" else "The assistant was interrupted."
    )
    remaining = sum(
        not item.product_id or (bool(plan.recipe_plan_id) and item.status != "matched")
        for item in plan.ingredients
    )
    status = (
        f"{remaining} ingredients still need catalog matches."
        if remaining
        else "The ingredients have catalog selections; basket checks are unfinished."
    )
    return (
        f"{cause} Your reviewed recipe progress is saved. {status} "
        "Continue this conversation to finish the basket checks and any missing delivery details; "
        "no purchase was authorized."
    )
