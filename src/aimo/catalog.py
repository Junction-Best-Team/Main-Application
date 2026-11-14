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
    return reasons


def quantity(p: dict, amount: Decimal, unit: str, whole_packs: bool) -> dict:
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
    per_sales = None
    if unit == p["sales_unit"]:
        per_sales = Fraction(1)
        result["basis"] = ["salesUnit"]
    elif unit in factors and factors[unit] > 0:
        per_sales = sales / factors[unit]
        result["basis"] = ["units.sizeInBaseUnits"]
    elif unit == "KG" and p["base_unit"] == "KG":
        per_sales = sales
        result["basis"] = ["baseUnit", "units.sizeInBaseUnits"]
    elif unit in p["measures"]:
        measure = p["measures"][unit]
        if measure["status"] == "conflicting":
            result["status"] = "conflicting"
            return result
        if measure["status"] == "known" and D(measure["value"]) > 0:
            per_sales = Fraction(measure["value"]) * sales
            result["basis"] = measure["basis"] + ["units.sizeInBaseUnits"]
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


def search_text(facts: dict) -> str:
    return " ".join(
        [facts["id"], facts.get("gtin") or "", *facts["names"].values(), *facts["claims"]]
    )
