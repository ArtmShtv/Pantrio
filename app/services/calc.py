"""Pure maths: unit conversion, nutrition, prices.

No FastAPI, no database. Everything takes plain values, so it is tested
with plain numbers (tests/test_calc.py).
"""

from decimal import Decimal

from app.db.models.enums import Unit

GRAMS = Decimal("0.01")
MONEY = Decimal("0.01")


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
    return (price / pack_size_g * 1000).quantize(MONEY)
