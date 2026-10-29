from decimal import Decimal as D

import pytest

from app.db.models.enums import Unit
from app.services.calc import UnitNotSupportedError, price_per_kg, to_grams


@pytest.mark.parametrize(
    ("quantity", "unit", "expected"),
    [
        (D("250"), Unit.G, D("250")),
        (D("930"), Unit.ML, D("957.9")),  # milk, 1.03 g/ml
        (D("2"), Unit.PIECE, D("110")),  # eggs, 55 g each
        (D("0.5"), Unit.PIECE, D("27.5")),
    ],
)
def test_to_grams(quantity, unit, expected):
    assert to_grams(quantity, unit, grams_per_piece=D("55"), grams_per_ml=D("1.03")) == expected


@pytest.mark.parametrize("unit", [Unit.ML, Unit.PIECE])
def test_to_grams_without_factor_raises(unit):
    with pytest.raises(UnitNotSupportedError, match=unit.value):
        to_grams(D("1"), unit, grams_per_piece=None, grams_per_ml=None)


def test_grams_need_no_factor():
    assert to_grams(D("5"), Unit.G, grams_per_piece=None, grams_per_ml=None) == D("5")


def test_price_per_kg_rounds_to_kopecks():
    assert price_per_kg(D("119.90"), D("900")) == D("133.22")
    assert price_per_kg(D("0"), D("500")) == D("0.00")
