"""Unit spellings and exact scales (server side only).

A model's plan or a request may say `l`, `liter`, `litres`, `ltr` or `kg`, `kilos`: they mean the
catalog codes L and KG exactly. `ml`, `cl`, `dl` and `g` are exact decimal fractions of L and KG
(1 ml = 0.001 L; 1 g = 0.001 kg). Nothing here knows a density, a pack or a piece, and any other
spelling (cup, tbsp, pcs, boxes) is left exactly as it was, so the conversion refuses it plainly.
"""

from fractions import Fraction

RENAMES = {
    "l": "L",
    "ltr": "L",
    "liter": "L",
    "liters": "L",
    "litre": "L",
    "litres": "L",
    "kg": "KG",
    "kilo": "KG",
    "kilos": "KG",
    "kilogram": "KG",
    "kilograms": "KG",
}
# spelling -> (catalog code, size of one such unit in that code)
SCALES = {
    "ml": ("L", Fraction(1, 1000)),
    "milliliter": ("L", Fraction(1, 1000)),
    "milliliters": ("L", Fraction(1, 1000)),
    "millilitre": ("L", Fraction(1, 1000)),
    "millilitres": ("L", Fraction(1, 1000)),
    "cl": ("L", Fraction(1, 100)),
    "dl": ("L", Fraction(1, 10)),
    "deciliter": ("L", Fraction(1, 10)),
    "deciliters": ("L", Fraction(1, 10)),
    "decilitre": ("L", Fraction(1, 10)),
    "decilitres": ("L", Fraction(1, 10)),
    "g": ("KG", Fraction(1, 1000)),
    "gram": ("KG", Fraction(1, 1000)),
    "grams": ("KG", Fraction(1, 1000)),
}


def catalog_unit(unit: str) -> str:
    """The catalog code for a pure spelling of L or KG; any other unit exactly as given."""
    return RENAMES.get(unit.strip().casefold(), unit)


def unit_scale(unit: str) -> tuple[str, Fraction]:
    """(catalog code, size of one `unit` in that code). 1 for a plain code or an unknown unit."""
    key = unit.strip().casefold()
    if key in SCALES:
        return SCALES[key]
    return catalog_unit(unit), Fraction(1)
