"""Pure policy evaluation. Facts cannot be repaired by a spending approval."""

from decimal import Decimal

DIETARY_FLAGS = ("lactose_free", "milk_free")


def trusted_constraints(constraints: list[dict] | None) -> list[dict]:
    """Customer-stated values only. An unconfirmed model assumption (POL-008) is never trusted,
    so it can neither loosen a limit nor be the reason a limit is skipped."""
    return [
        c
        for c in constraints or []
        if c.get("source") != "stated_assumption" or c.get("confirmed") is True
    ]


def evaluate_purchase(
    request: dict,
    snapshot: dict,
    rules: dict,
    approvers: list[dict],
    constraints: list[dict] | None = None,
) -> dict:
    """Spending authority belongs to the buyer's human approvers (their `max_gross`) and to the
    request's hard budget. Agent identities carry none (owner decision Q-35).

    `constraints` is a server-only record of what the customer stated (POL-008), never a model
    argument. The effective limit is the stricter of the request value and the trusted value."""
    reasons = list(snapshot["reasons"])
    exceptions = []

    def add(code, message, severity):
        reasons.append(dict(code=code, message=message, product_id=None, severity=severity))

    trusted = trusted_constraints(constraints)
    requirements = request.get("requirements") or {}
    budget = request.get("budget_gross")
    budget = Decimal(budget) if budget is not None else None
    stored_budgets = [Decimal(str(c["value"])) for c in trusted if c["name"] == "budget_gross"]
    if stored_budgets:
        stored = min(stored_budgets)
        if budget is not None and budget > stored:
            add(
                "CONSTRAINT_LOOSENED",
                f"The request budget_gross {budget} is looser than the customer's {stored}; "
                "ask the customer.",
                "unresolved",
            )
        # A missing or looser budget is enforced at the customer's number.
        budget = stored if budget is None else min(budget, stored)
    for flag in DIETARY_FLAGS:
        if any(c["name"] == flag and c["value"] is True for c in trusted) and not requirements.get(
            flag
        ):
            add(
                "CONSTRAINT_LOOSENED",
                f"The customer required {flag} but the request does not; ask the customer.",
                "unresolved",
            )
    stated_unsupported = {u.casefold() for u in requirements.get("unsupported") or []}
    for c in trusted:
        text = c["name"].removeprefix("unsupported:")
        if (
            c["name"].startswith("unsupported:")
            and c["value"] is True
            and text.casefold() not in stated_unsupported
        ):
            add(
                "CONSTRAINT_LOOSENED",
                f"The customer's requirement '{text}' is missing from the request; "
                "ask the customer.",
                "unresolved",
            )

    if not rules:
        add("MISSING_AUTHORITY", "Buyer policy is missing.", "unresolved")
    if rules and request["destination"] not in rules.get("destinations", []):
        add("DESTINATION_NOT_ALLOWED", "Destination is outside the buyer policy.", "denied")
    if not snapshot["currency"] or not rules.get("currency"):
        add("CURRENCY_UNRESOLVED", "Currency or its authority is not established.", "unresolved")
    elif snapshot["currency"] != rules["currency"]:
        add("CURRENCY_NOT_ALLOWED", "Currency is outside current authority.", "denied")
    for item in (request.get("requirements") or {}).get("unsupported") or []:
        # POL-009: a stated requirement the system cannot verify is never silently dropped.
        add(
            "REQUIREMENT_UNSUPPORTED",
            f"The requirement '{item}' cannot be verified against the catalog; ask the customer.",
            "unresolved",
        )
    total = Decimal(snapshot["gross_total"]) if snapshot["gross_total"] is not None else None
    if total is None and not any(r["code"] == "TOTAL_UNRESOLVED" for r in reasons):
        # Owner decision (Q-30, POL-009): readiness never depends on the caller having reported
        # an unknown total; every spending rule below is skipped when the total is unknown.
        add("TOTAL_UNRESOLVED", "Complete gross payable cannot be established.", "unresolved")
    if total is not None and budget is not None and total > budget:
        add(
            "HARD_BUDGET_EXCEEDED",
            "Gross payable exceeds the mission budget; revise the request.",
            "denied",
        )
    cap = rules.get("max_order_gross")
    if total is not None and cap is not None and total > Decimal(str(cap)):
        add(
            "ACCOUNT_CAP_EXCEEDED",
            "Gross payable exceeds the account spending cap; revise the basket or account cap.",
            "denied",
        )
    approved_ids = rules.get("approved_product_ids")
    if approved_ids is None:
        # Owner decision 2026-11-14 (POL-004): missing trusted scope always blocks, whatever the
        # substitution setting. Only privileged setup can configure it; approval cannot repair it.
        add(
            "PRODUCT_SCOPE_UNCONFIGURED",
            "A buyer-approved product scope must be configured before a purchase can be committed.",
            "unresolved",
        )
    outside_scope = approved_ids is not None and any(
        line["product_id"] not in approved_ids for line in request["lines"]
    )
    for kind, present in [
        (
            "substitution",
            outside_scope or any(line.get("substitutes_for") for line in request["lines"]),
        ),
        (
            "overbuy",
            any(Decimal(line["quantity"].get("excess") or "0") > 0 for line in snapshot["lines"]),
        ),
    ]:
        if not present:
            continue
        rule = rules.get(kind, "forbidden")
        if rule == "forbidden" or not request.get(f"allow_{kind}", True):
            add(
                f"{kind.upper()}_FORBIDDEN",
                f"{kind.title()} is forbidden by this purchase or policy.",
                "denied",
            )
        elif rule == "requires_approval":
            exceptions.append(kind)
            add(
                f"{kind.upper()}_REQUIRES_APPROVAL",
                "Product selection is outside the buyer-approved scope or declares a substitution."
                if kind == "substitution"
                else f"{kind.title()} needs a buyer decision.",
                "exception",
            )
        elif kind == "substitution":
            # Owner decision 2026-11-14 (POL-006): policy "allowed" is a permitted exception, so
            # no approval is required, but each such line is recorded in the proposal and audit log.
            for line in request["lines"]:
                if line.get("substitutes_for") or (
                    approved_ids is not None and line["product_id"] not in approved_ids
                ):
                    reasons.append(
                        dict(
                            code="SUBSTITUTION_ALLOWED_BY_POLICY",
                            message="Product is outside the approved scope or declares a "
                            "substitution; buyer policy allows this without approval.",
                            product_id=line["product_id"],
                            severity="exception",
                        )
                    )
    if total is not None and not any(
        can_approve(a, total, rules.get("currency"), exceptions) for a in approvers
    ):
        # Owner decision Q-37 (POL-014): unconditional. Someone must be able to confirm this
        # total, so a total above every active approver's maximum, or no active approver at
        # all, is needs_resolution even when no exception is in play.
        add(
            "NO_ELIGIBLE_APPROVER",
            "No current approver covers the amount and every exception.",
            "unresolved",
        )
    severities = {r["severity"] for r in reasons}
    outcome = (
        "denied"
        if "denied" in severities
        else "needs_resolution"
        if "unresolved" in severities
        else "approval_required"
        if exceptions
        else "ready_to_commit"
    )
    return {"policy_outcome": outcome, "reasons": reasons, "required_exceptions": exceptions}


def can_approve(authority: dict, total: Decimal, currency: str, exceptions: list[str]) -> bool:
    return (
        authority.get("currency") == currency
        and total <= Decimal(authority.get("max_gross", "0"))
        and set(exceptions) <= set(authority.get("exceptions", []))
    )
