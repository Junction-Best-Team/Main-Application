"""Conservative normalization: source facts stay distinct from inferred descriptions."""

import re
from decimal import Decimal
from fractions import Fraction
from math import ceil, lcm

from aimo.numeric import D, fraction_text
from aimo.schemas import Requirements

VOLUME = {"LTR": D(1), "MLT": D(".001"), "CLT": D(".01"), "DLT": D(".1")}
MASS = {"KGM": D(1), "GRM": D(".001")}


def normalize(raw: dict, source: str) -> dict:
    s = raw.get("synkkaData") or {}
    names = {n["language"]: n["value"] for n in s.get("names", [])}
    groups = {}
    for group in s.get("classifications", []):
        groups.setdefault(group["name"], []).extend(group.get("values", []))
    present = {
        v["id"]: v.get("unit")
        for v in groups.get("allergen", [])
        if v.get("unit") in ("CONTAINS", "MAY_CONTAIN")
    }
    absent = {v["id"] for v in groups.get("nonAllergen", []) if v.get("unit") == "FREE_FROM"}
    claims = [v["id"] for v in groups.get("nutritionalClaim", [])]
    units = {}
    conflicts = []
    for u in raw.get("units", []):
        value = str(u["sizeInBaseUnits"])
        if u["unitId"] in units and D(units[u["unitId"]]) != D(value):
            conflicts.append("UNIT_FACTOR_CONFLICT")
        units[u["unitId"]] = value
    measurements = {"L": [], "KG": []}
    for entry in s.get("unitConversions", []):
        if entry.get("synkkaPackagingType") != "BASE_UNIT_OR_EACH":
            continue
        for field, mapping, target in [("volume", VOLUME, "L"), ("netWeight", MASS, "KG")]:
            value = entry.get(field) or {}
            if value.get("unit") in mapping and value.get("value") is not None:
                measurements[target].append(
                    (
                        D(value["value"]) * mapping[value["unit"]],
                        f"synkkaData.unitConversions.BASE_UNIT_OR_EACH.{field}",
                    )
                )
    measures = {}
    for unit, values in measurements.items():
        distinct = {v for v, _ in values}
        status = "known" if len(distinct) == 1 else ("conflicting" if distinct else "unknown")
        measures[unit] = {
            "value": str(values[0][0]) if len(distinct) == 1 else None,
            "status": status,
            "basis": [p for _, p in values],
        }
    # Names are corroboration only. Never turn a marketing size into a physical conversion.
    name = names.get("en", names.get("fi", next(iter(names.values()), raw["id"])))
    match = re.search(r"(?<![\dx×])\b(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|l)\b", name, re.I)
    if match and not re.search(r"\d\s*[x×]", name):
        inferred = (
            D(match[1].replace(",", "."))
            * {"ml": D(".001"), "cl": D(".01"), "dl": D(".1"), "l": D(1)}[match[2].lower()]
        )
        measures["L"]["name_hint"] = str(inferred)
        if measures["L"]["status"] == "known" and abs(D(measures["L"]["value"]) - inferred) > D(
            ".001"
        ):
            measures["L"]["status"] = "conflicting"
    return {
        "id": raw["id"],
        "name": name,
        "names": names,
        "gtin": raw.get("salesUnitGtin"),
        "sales_unit": raw.get("salesUnit"),
        "base_unit": raw.get("baseUnit"),
        "units": units,
        "order_step": str(raw.get("allowedLotSize", "0")),
        "measures": measures,
        "variable_weight": s.get("variableUnit") is not False,
        "claims": claims,
        "allergens": present,
        "free_from": sorted(absent),
        "allergen_conflicts": sorted(set(present) & absent),
        "conflicts": conflicts,
        "deposits": raw.get("deposits", []),
        "substitutions": raw.get("substitutions", []),
        "category": raw.get("category"),
        "country_of_origin": raw.get("countryOfOrigin"),
        "deleted": raw.get("deleted", False),
        "provenance": {"source": source, "product_id": raw["id"]},
        "packaging": s.get("unitConversions", []),
        "brand": s.get("brand"),
        "vendor_name": raw.get("vendorName"),
        # Discovery-only source descriptions; never used to establish dietary safety.
        "descriptions": [
            {"language": item["language"], "value": item["value"][:600]}
            for field in ("materialAdditionalDescriptions", "marketingTexts")
            for item in (s.get(field) or [])
            if item.get("language") in ("fi", "en", "sv") and item.get("value")
        ][:6],
    }


def requirement_reasons(p: dict, requirements: Requirements) -> list[dict]:
    reasons = []

    def add(code, message, severity="unresolved"):
        reasons.append(dict(code=code, message=message, product_id=p["id"], severity=severity))

    if p["allergen_conflicts"]:
        add("DIETARY_EVIDENCE_CONFLICT", "Allergen and free-from declarations conflict.")
    if requirements.lactose_free and "FREE_FROM_LACTOSE" not in p["claims"]:
        add("LACTOSE_FREE_UNVERIFIED", "An explicit lactose-free claim is missing.")
    if requirements.milk_free:
        if "AM" in p["allergen_conflicts"]:
            pass
        elif "AM" in p["allergens"]:
            add(
                "MILK_REQUIREMENT_VIOLATED", "Milk is declared present or may be present.", "denied"
            )
        elif "AM" not in p["free_from"]:
            add("MILK_FREE_UNVERIFIED", "An explicit milk-free declaration is missing.")
    for code in requirements.free_from:
        if code in p["allergen_conflicts"]:
            continue
        if code in p["allergens"]:
            add(
                "FREE_FROM_REQUIREMENT_VIOLATED",
                f"Allergen {code} is declared present or may be present.",
                "denied",
            )
        elif code not in p["free_from"]:
            add("FREE_FROM_UNVERIFIED", f"An explicit {code}-free declaration is missing.")
    if requirements.country_of_origin:
        origin = (p.get("country_of_origin") or "").lower()
        if not origin:
            add("ORIGIN_UNVERIFIED", "The country of origin is not recorded.")
        elif origin not in requirements.country_of_origin:
            add(
                "ORIGIN_REQUIREMENT_VIOLATED",
                f"Country of origin {origin} is not among the requested origins.",
                "denied",
            )
    return reasons


# Configured unit priority for one product requested in several units: KG, then L, then any
# other unit (pieces). BAS-009.
UNIT_PRIORITY = ("KG", "L")


def per_sales_for(p: dict, unit: str, count_evidence=None) -> tuple:
    """Requested-unit amount in one sales unit, from catalog evidence only.

    Returns (per_sales or None, basis, conflicting). Shared by `quantity` and
    `combine_in_priority_unit`; the sales unit must already have a positive factor.
    """
    factors = {k: Fraction(v) for k, v in p["units"].items()}
    sales = factors[p["sales_unit"]]
    per_sales, basis = None, []
    if unit == "piece" and count_evidence:
        per_sales = Fraction(count_evidence["piece_per_sales"])
        basis = [count_evidence["source"], "reviewed_ingredient_count_per_sales_unit"]
    elif unit == p["sales_unit"]:
        per_sales = Fraction(1)
        basis = ["salesUnit"]
    elif unit in factors and factors[unit] > 0:
        per_sales = sales / factors[unit]
        basis = ["units.sizeInBaseUnits"]
    elif unit == "KG" and p["base_unit"] == "KG":
        per_sales = sales
        basis = ["baseUnit", "units.sizeInBaseUnits"]
    elif unit in p["measures"]:
        measure = p["measures"][unit]
        if measure["status"] == "conflicting":
            return None, [], True
        if measure["status"] == "known" and D(measure["value"]) > 0:
            per_sales = Fraction(measure["value"]) * sales
            basis = measure["basis"] + ["units.sizeInBaseUnits"]
    return per_sales, basis, False


def quantity(
    p: dict, amount: Decimal, unit: str, whole_packs: bool, *, count_evidence=None
) -> dict:
    result = {
        "requested_amount": str(amount),
        "requested_unit": unit,
        "sales_unit": p["sales_unit"],
        "sales_quantity": None,
        "proposed_amount": None,
        "excess": None,
        "status": "unknown",
        "basis": [],
        "source_step": p["order_step"],
    }
    factors = {k: Fraction(v) for k, v in p["units"].items()}
    sales = factors.get(p["sales_unit"])
    if not sales or sales <= 0 or p["conflicts"]:
        return result
    per_sales, result["basis"], conflicting = per_sales_for(p, unit, count_evidence)
    if conflicting:
        result["status"] = "conflicting"
        return result
    if not per_sales:
        return result
    step = Fraction(p["order_step"])
    if step <= 0:
        return result
    # Buyer rule, not a reinterpretation of the source's frequent 0.01 steps.
    if whole_packs and p["sales_unit"] != "KG":
        step = Fraction(lcm(step.numerator, step.denominator), step.denominator)
        result["basis"].append("buyer_policy.whole_sales_units")
    requested = Fraction(amount)
    sales_quantity = ceil(requested / per_sales / step) * step
    proposed = sales_quantity * per_sales
    result.update(
        sales_quantity=fraction_text(sales_quantity),
        proposed_amount=fraction_text(proposed),
        excess=fraction_text(proposed - requested),
        effective_step=fraction_text(step),
        status="derived",
    )
    return result


def line_weight_kg(
    p: dict, amount: Decimal, unit: str, whole_packs: bool, count_evidence=None
) -> Fraction | None:
    """Kilograms actually bought for one line (MEA-011): the whole sales units the basket
    proposes times the kilograms in one sales unit, from catalogue evidence only (the sales unit
    is KG, the units table lists KG, or a known KG measure). None when there is no kilogram
    evidence; a litre or piece product without a weight is never guessed."""
    q = quantity(p, Decimal(amount), unit, whole_packs, count_evidence=count_evidence)
    if q["sales_quantity"] is None:
        return None
    if not {"sales_unit", "units"} <= p.keys() or not p["units"].get(p["sales_unit"]):
        return None
    per_sales, _, conflicting = per_sales_for(p, "KG")
    if conflicting or not per_sales:
        return None
    return Fraction(q["sales_quantity"]) * per_sales


def _unknown_combination(reason: str) -> dict:
    return {"amount": None, "unit": None, "status": "unknown", "basis": [], "reason": reason}


def combine_in_priority_unit(
    p: dict, items: list[tuple[Decimal, str]], *, count_evidence=None
) -> dict:
    """Sum amounts of ONE product requested in several units, in one priority unit (BAS-009).

    Each amount goes to sales units with exact `Fraction` arithmetic and the same catalog
    evidence as `quantity`; nothing is guessed or rounded. The unit is the first of
    `UNIT_PRIORITY` among the requested units, else the sales unit if requested, else the
    alphabetically first requested unit (never the request order, so the result is stable).
    """
    if not items:
        return _unknown_combination("No quantities were given.")
    factors = {k: Fraction(v) for k, v in p["units"].items()}
    sales = factors.get(p["sales_unit"])
    if not sales or sales <= 0 or p["conflicts"]:
        return _unknown_combination("The product's unit facts are missing or conflict.")
    total, basis, per_sales = Fraction(0), [], {}
    for amount, unit in items:
        if amount <= 0:
            return _unknown_combination(f"The amount in {unit} must be positive.")
        if unit not in per_sales:
            factor, unit_basis, conflicting = per_sales_for(p, unit, count_evidence)
            if conflicting or not factor:
                return _unknown_combination(
                    f"No catalog evidence converts {unit} to the sales unit."
                )
            per_sales[unit] = factor
            basis.extend(b for b in unit_basis if b not in basis)
        total += Fraction(amount) / per_sales[unit]
    requested = set(per_sales)
    chosen = next((u for u in UNIT_PRIORITY if u in requested), None)
    if chosen is None:
        chosen = p["sales_unit"] if p["sales_unit"] in requested else min(requested)
    exact = total * per_sales[chosen]
    if (exact * 10_000).denominator != 1:
        return _unknown_combination(
            f"The exact total in {chosen} needs more than 4 decimal places."
        )
    text = fraction_text(exact)
    digits = Decimal(text).as_tuple()
    if max(len(digits.digits), -digits.exponent) > 14:
        return _unknown_combination(f"The exact total in {chosen} needs more than 14 digits.")
    return {
        "amount": text,
        "unit": chosen,
        "status": "derived",
        "basis": [*sorted(basis), "unit_priority"],
    }


def search_text(facts: dict) -> str:
    return " ".join(
        [facts["id"], facts.get("gtin") or "", *facts["names"].values(), *facts["claims"]]
    )


def rich_search_text(facts: dict) -> str:
    """Bounded source-backed discovery text; opaque codes are not translated/guessed."""
    lines = [search_text(facts)]
    for field in ("brand", "vendor_name", "sales_unit", "base_unit", "country_of_origin"):
        if facts.get(field):
            lines.append(f"{field}: {facts[field]}")
    for item in facts.get("descriptions", []):
        lines.append(f"Description ({item['language']}): {item['value']}")
    return "\n".join(lines)[:8000]
