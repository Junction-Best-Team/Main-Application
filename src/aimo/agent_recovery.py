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


def progress_status(session):
    """What this turn got done, in one plain sentence, for the texts that end a turn early."""
    if session.prepared_digest is not None and session.proposal:
        if session.proposal.get("policy_outcome") in ("denied", "needs_resolution"):
            return "The basket is prepared but blocked; the reasons are shown with it."
        return "The basket is prepared; review it and press Confirm purchase."
    plan = session.plan
    if plan and plan.ingredients:
        items = [i for i in plan.ingredients if i.status != "removed" and not is_removed(i)]
        matched = sum(
            bool(i.product_id) and (not plan.recipe_plan_id or i.status == "matched") for i in items
        )
        left = len(items) - matched
        return f"The plan has {matched} of {len(items)} ingredients matched" + (
            f"; {left} still need a product." if left else "; no basket was prepared yet."
        )
    return "No plan or basket was made yet."


def is_removed(item):
    return str(item.amount) in ("0", "0.0")
