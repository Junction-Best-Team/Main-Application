"""Exact quantity arithmetic; Decimal remains the money representation."""

from decimal import Decimal, localcontext
from fractions import Fraction


def D(value):
    return Decimal(str(value))


def fraction_text(value: Fraction) -> str:
    # Presentation only: all rounding decisions and excess calculations use Fraction.
    with localcontext() as ctx:
        ctx.prec = max(50, len(str(abs(value.numerator))) + len(str(value.denominator)) + 4)
        return format(Decimal(value.numerator) / Decimal(value.denominator), "f")
