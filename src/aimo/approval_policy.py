"""Pure policy evaluation. Facts cannot be repaired by a spending approval."""

from decimal import Decimal


def evaluate_purchase(
    request: dict, snapshot: dict, rules: dict, authority: dict, approvers: list[dict]
) -> dict:
    reasons = list(snapshot["reasons"])
    exceptions = []

    def add(code, message, severity):
        reasons.append(dict(code=code, message=message, product_id=None, severity=severity))

    if not rules or not authority:
        add("MISSING_AUTHORITY", "Buyer policy or agent authority is missing.", "unresolved")
    if rules and request["destination"] not in rules.get("destinations", []):
        add("DESTINATION_NOT_ALLOWED", "Destination is outside the buyer policy.", "denied")
    if not snapshot["currency"] or not rules.get("currency") or not authority.get("currency"):
        add("CURRENCY_UNRESOLVED", "Currency or its authority is not established.", "unresolved")
    elif snapshot["currency"] != rules["currency"] or authority["currency"] != rules["currency"]:
        add("CURRENCY_NOT_ALLOWED", "Currency is outside current authority.", "denied")
    total = Decimal(snapshot["gross_total"]) if snapshot["gross_total"] is not None else None
    if (
        total is not None
        and request.get("budget_gross") is not None
        and total > Decimal(request["budget_gross"])
    ):
        add(
            "HARD_BUDGET_EXCEEDED",
            "Gross payable exceeds the mission budget; revise the request.",
            "denied",
        )
    for kind, present in [
        ("substitution", any(line.get("substitutes_for") for line in request["lines"])),
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
                f"{kind.title()} needs a buyer decision.",
                "exception",
            )
    limit = min(
        Decimal(rules.get("autonomous_limit", "0")), Decimal(authority.get("autonomous_limit", "0"))
    )
    if total is not None and total > limit:
        exceptions.append("spend")
        add(
            "AUTONOMOUS_LIMIT_EXCEEDED",
            f"Gross payable exceeds autonomous authority of {limit}.",
            "exception",
        )
    if (
        exceptions
        and total is not None
        and not any(can_approve(a, total, rules.get("currency"), exceptions) for a in approvers)
    ):
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
