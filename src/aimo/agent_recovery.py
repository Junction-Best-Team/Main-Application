"""Deterministic interruption copy; no inferred recipe evidence or authority."""


def partial_notice(plan, code):
    cause = (
        "I reached the time limit." if code == "LLM_TIMEOUT" else "The assistant was interrupted."
    )
    remaining = sum(
        not item.product_id or (bool(plan.recipe_plan_id) and item.status != "matched")
        for item in plan.ingredients
    )
    status = (
        (
            "1 ingredient still needs a catalog match."
            if remaining == 1
            else f"{remaining} ingredients still need catalog matches."
        )
        if remaining
        else "The ingredients have catalog selections."
    )
    return (
        f"{cause} Your reviewed recipe progress is saved. {status} "
        "Review any prepared basket, or continue here for remaining basket checks and delivery details; "
        "no purchase was authorized."
    )
