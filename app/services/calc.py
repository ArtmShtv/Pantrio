"""Pure maths: unit conversion, nutrition, prices.

No FastAPI, no database. Everything takes plain values, so it is tested
with plain numbers (tests/test_calc.py).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.db.models.enums import Unit

GRAMS = Decimal("0.01")
MONEY = Decimal("0.01")
ONE_DECIMAL = Decimal("0.1")


def round_to(value: Decimal, step: Decimal) -> Decimal:
    # Half-up, as people expect: 0.25 -> 0.3. Decimal's default is banker's
    # rounding (half-even), where 0.25 -> 0.2 but 0.35 -> 0.4.
    return value.quantize(step, rounding=ROUND_HALF_UP)


class UnitNotSupportedError(ValueError):
    def __init__(self, unit: Unit) -> None:
        super().__init__(f"this ingredient can't be measured in {unit.value}")
        self.unit = unit


def to_grams(
    quantity: Decimal,
    unit: Unit,
    *,
    grams_per_piece: Decimal | None,
    grams_per_ml: Decimal | None,
) -> Decimal:
    match unit:
        case Unit.G:
            return quantity
        case Unit.ML:
            factor = grams_per_ml
        case Unit.PIECE:
            factor = grams_per_piece
    if factor is None:
        raise UnitNotSupportedError(unit)
    return quantity * factor


def price_per_kg(price: Decimal, pack_size_g: Decimal) -> Decimal:
    return round_to(price / pack_size_g * 1000, MONEY)


@dataclass(frozen=True)
class Nutrition:
    """Unrounded totals. Round only when building a response."""

    grams: Decimal = Decimal(0)
    kcal: Decimal = Decimal(0)
    protein: Decimal = Decimal(0)
    fat: Decimal = Decimal(0)
    carbs: Decimal = Decimal(0)

    def __add__(self, other: "Nutrition") -> "Nutrition":
        return Nutrition(
            self.grams + other.grams,
            self.kcal + other.kcal,
            self.protein + other.protein,
            self.fat + other.fat,
            self.carbs + other.carbs,
        )

    def scale(self, factor: Decimal) -> "Nutrition":
        return Nutrition(
            self.grams * factor,
            self.kcal * factor,
            self.protein * factor,
            self.fat * factor,
            self.carbs * factor,
        )


def nutrition_for(
    grams: Decimal, *, calories: Decimal, protein: Decimal, fat: Decimal, carbs: Decimal
) -> Nutrition:
    """Nutrition of `grams` of an ingredient given its per-100 g values."""
    f = grams / 100
    return Nutrition(grams, calories * f, protein * f, fat * f, carbs * f)


def total(parts: Iterable[Nutrition]) -> Nutrition:
    return sum(parts, Nutrition())
