"""Small authored fixture projections. Prices/stock are invented, not captured live data."""

from copy import deepcopy


def fixture_facts():
    base = {
        "id": "464306",
        "name": "Demo Arki Eila milk drink 1 L",
        "names": {
            "en": "Demo lactose-free milk drink 1 L",
            "fi": "Demo laktoositon kevytmaitojuoma 1 l",
        },
        "gtin": None,
        "sales_unit": "ST",
        "base_unit": "ST",
        "units": {"ST": "1", "KI": "20"},
        "order_step": ".01",
        "measures": {
            "L": {"value": "1", "status": "known", "basis": ["fixture.base_volume"]},
            "KG": {"value": None, "status": "unknown", "basis": []},
        },
        "variable_weight": False,
        "claims": ["FREE_FROM_LACTOSE"],
        "allergens": {"AM": "CONTAINS"},
        "free_from": [],
        "allergen_conflicts": [],
        "conflicts": [],
        "deposits": [],
        "substitutions": [],
        "category": "fixture",
        "country_of_origin": "fi",
        "deleted": False,
        "packaging": [],
        "provenance": {"source": "authored fixture; not live catalog", "product_id": "464306"},
    }
    rows = []
    for pid, name in [
        ("464306", base["name"]),
        ("464398", "Demo UHT lactose-free milk 1 L"),
        ("463380", "Demo shortage milk 1 L"),
        ("465039", "Demo milk 5-pack (volume unverified)"),
        ("460123", "Demo Vitamin Well 12 bottles"),
        ("460675", "Demo variable-weight flank steak"),
        ("460035", "Demo lettuce mix"),
        ("468044", "Demo conflicting milk allergen"),
        ("469429", "Demo conflicting may-contain allergen"),
    ]:
        p = deepcopy(base)
        p.update(
            id=pid,
            name=name,
            names={
                "en": name,
                "fi": base["names"]["fi"]
                if pid in ("464306", "464398", "463380", "465039")
                else name,
            },
        )
        p["provenance"]["product_id"] = pid
        if pid == "465039":
            p.update(sales_unit="KI", units={"ST": "1", "KI": "5"})
            p["measures"]["L"] = {"value": None, "status": "unknown", "basis": [], "name_hint": "1"}
        if pid == "460123":
            p.update(
                sales_unit="KI",
                base_unit="BOT",
                units={"BOT": "1", "KI": "12"},
                deposits=[{"material": "demo-deposit", "quantity": "12", "unit": "ST"}],
            )
            p["measures"]["L"]["value"] = ".5"
        if pid in ("460675", "460035"):
            p.update(
                sales_unit="KG",
                base_unit="KG",
                units={"KG": "1"},
                order_step="10" if pid == "460675" else "3",
                variable_weight=True,
                claims=[],
                allergens={},
            )
            p["measures"]["L"] = {"value": None, "status": "unknown", "basis": []}
        if pid in ("468044", "469429"):
            p.update(
                allergens={"AM": "CONTAINS" if pid == "468044" else "MAY_CONTAIN"},
                free_from=["AM"],
                allergen_conflicts=["AM"],
            )
        rows.append(p)
    deposit = deepcopy(base)
    deposit.update(
        id="demo-deposit",
        name="Demo returnable bottle deposit",
        names={"en": "Demo bottle deposit"},
        units={"ST": "1"},
        claims=[],
        allergens={},
    )
    deposit["provenance"]["product_id"] = "demo-deposit"
    rows.append(deposit)
    return rows
