"""Basket refusals that tell the agent exactly what to send (Q-44, BAS-009).

A basket whose units differ from the saved plan stays refused. The error carries, as structured
`details`, the amount and unit of every product the agent has to send, plus what was wrong with
what it sent. Amounts are exact decimal strings (`Fraction` arithmetic, never float).
"""

from decimal import Decimal
from fractions import Fraction

from aimo.catalog import combine_in_priority_unit
from aimo.db import Problem
from aimo.numeric import fraction_text


class BasketProblem(Problem):
    """A `Problem` that also carries structured `details` for the client and the model."""

    def __init__(self, code: str, message: str, details: dict, status: int = 422):
        super().__init__(code, message, status)
        self.details = details


def _fraction(value) -> Fraction:
    if isinstance(value, float):
        raise TypeError("Amounts must be Decimal, int or str, never float.")
    return Fraction(value)


def _text(value: Fraction) -> str:
    return fraction_text(value)


def _field(line, name):
    return line[name] if isinstance(line, dict) else getattr(line, name)


def _combine(product_id, items, products):
    """items: [(Fraction, unit)] of one product -> (Fraction, unit) or (None, reason)."""
    units = {unit for _, unit in items}
    if len(units) == 1:
        return sum((amount for amount, _ in items), Fraction(0)), units.pop()
    product = (products or {}).get(product_id)
    if product is None:
        return None, "The product facts are not loaded."
    result = combine_in_priority_unit(
        product, [(Decimal(_text(amount)), unit) for amount, unit in items]
    )
    if result["status"] != "derived":
        return None, result["reason"]
    return Fraction(result["amount"]), result["unit"]


def required_basket(contributions, products=None) -> list[dict]:
    """Per product, the amount and unit the agent must send, from the plan's contributions.

    One unit across the contributions is a plain sum in that unit. Several units are converted
    with catalog evidence and combined in the priority unit; no evidence gives `amount None`.
    """
    grouped = {}
    for c in contributions:
        grouped.setdefault(c["product_id"], []).append(c)
    required = []
    for product_id in sorted(grouped):
        rows = grouped[product_id]
        names = sorted({n for r in rows if (n := r.get("name") or r.get("ingredient_id"))})
        amount, unit = _combine(
            product_id, [(_fraction(r["amount"]), r["unit"]) for r in rows], products
        )
        if amount is None:
            required.append(
                {"product_id": product_id, "amount": None, "unit": None, "reason": unit}
                | {"ingredients": names}
            )
        else:
            required.append(
                {
                    "product_id": product_id,
                    "amount": _text(amount),
                    "unit": unit,
                    "ingredients": names,
                }
            )
    return required


def mismatch_details(required, sent_lines, products=None) -> dict:
    """Compare what the agent sent with `required_basket(...)`; list every difference."""
    sent_by = {}
    for line in sent_lines:
        sent_by.setdefault(_field(line, "product_id"), []).append(
            (_fraction(_field(line, "amount")), _field(line, "unit"))
        )
    wanted = {r["product_id"]: r for r in required}
    sent = sorted(
        (
            {"product_id": pid, "amount": _text(amount), "unit": unit}
            for pid, items in sent_by.items()
            for amount, unit in items
        ),
        key=lambda s: (s["product_id"], s["unit"], Fraction(s["amount"])),
    )
    missing, wrong = [], []
    for pid in sorted(wanted):
        entry = wanted[pid]
        if pid not in sent_by:
            missing.append(pid)
            continue
        if entry["amount"] is None:
            continue  # nothing exact to compare with: the unit conversion error covers it
        amount, unit = _combine(pid, sent_by[pid], products)
        if amount is None or (_text(amount), unit) != (entry["amount"], entry["unit"]):
            shown = (
                {"amount": None, "unit": None}
                if amount is None
                else {
                    "amount": _text(amount),
                    "unit": unit,
                }
            )
            if len(sent_by[pid]) > 1:
                shown["lines"] = [
                    {"amount": _text(a), "unit": u} for a, u in sorted(sent_by[pid], key=_line_key)
                ]
            wrong.append(
                {
                    "product_id": pid,
                    "required": {"amount": entry["amount"], "unit": entry["unit"]},
                    "sent": shown,
                }
            )
    return {
        "required": sorted(required, key=lambda r: r["product_id"]),
        "sent": sent,
        "missing": missing,
        "unexpected": sorted(pid for pid in sent_by if pid not in wanted),
        "wrong_amount_or_unit": wrong,
    }


def _line_key(item):
    return item[1], item[0]


def _required_line(entry) -> str:
    if entry["amount"] is None:
        return f"{entry['product_id']} (no single unit: {entry['reason']})"
    return f"{entry['product_id']} {entry['amount']} {entry['unit']}"


def mismatch_problem(required, sent_lines, products=None) -> BasketProblem:
    """MEAL_BASKET_MISMATCH with the exact lines to send, in the message and in `details`."""
    details = mismatch_details(required, sent_lines, products)
    parts = [
        "The basket does not match the saved recipe plan. Send exactly: "
        + "; ".join(_required_line(r) for r in details["required"])
        + "."
    ]
    if details["missing"]:
        parts.append("Missing: " + ", ".join(details["missing"]) + ".")
    if details["unexpected"]:
        parts.append("Not in the plan, remove: " + ", ".join(details["unexpected"]) + ".")
    for w in details["wrong_amount_or_unit"]:
        want, got = w["required"], w["sent"]
        sent_text = (
            "nothing convertible" if got["amount"] is None else f"{got['amount']} {got['unit']}"
        )
        parts.append(f"{w['product_id']}: sent {sent_text}, needs {want['amount']} {want['unit']}.")
    parts.append("Use these units and amounts; do not convert or round them.")
    return BasketProblem("MEAL_BASKET_MISMATCH", " ".join(parts), details)


def unit_conversion_problem(product_id, required, needed=None) -> BasketProblem:
    """UNIT_CONVERSION_UNKNOWN: one product is needed in several units with no catalog evidence.

    `required` is the product's `required_basket` entry or the whole list; `needed` optionally
    lists the plan's `(amount, unit)` contributions for the product.
    """
    rows = [required] if isinstance(required, dict) else list(required)
    entry = next(r for r in rows if r["product_id"] == product_id)
    details = {
        "product_id": product_id,
        "reason": entry.get("reason"),
        "required": rows,
    }
    message = (
        f"Product {product_id} is needed in several units and the catalog cannot combine them: "
        f"{entry.get('reason')} Change the recipe plan so this product is in one unit, then "
        "send that amount and unit."
    )
    if needed:
        details["needed_in"] = [
            {"amount": _text(_fraction(a)), "unit": u}
            for a, u in sorted(needed, key=lambda x: (x[1], _fraction(x[0])))
        ]
        message += (
            " Needed: "
            + "; ".join(f"{d['amount']} {d['unit']}" for d in details["needed_in"])
            + "."
        )
    return BasketProblem("UNIT_CONVERSION_UNKNOWN", message, details)
