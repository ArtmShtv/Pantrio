from decimal import Decimal as D

import pytest

from app.db.models.enums import Unit
from app.services.calc import (
    ONE_DECIMAL,
    Nutrition,
    UnitNotSupportedError,
    nutrition_for,
    price_per_kg,
    round_to,
    to_grams,
    total,
)


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


# --- nutrition ---------------------------------------------------------------

RICE = {"calories": D("344"), "protein": D("6.7"), "fat": D("0.7"), "carbs": D("78.9")}
MILK = {"calories": D("60"), "protein": D("3"), "fat": D("3.2"), "carbs": D("4.7")}


def test_nutrition_for_grams():
    n = nutrition_for(D("150"), **RICE)
    assert n == Nutrition(D("150"), D("516"), D("10.05"), D("1.05"), D("118.35"))


def test_ml_to_grams_to_kcal():
    grams = to_grams(D("200"), Unit.ML, grams_per_piece=None, grams_per_ml=D("1.03"))
    assert nutrition_for(grams, **MILK).kcal == D("123.6")


def test_total_and_scale():
    a = nutrition_for(D("100"), **RICE)
    assert total([a, a]) == a.scale(D(2))
    assert total([]) == Nutrition()


@pytest.mark.parametrize(
    ("value", "expected"),
    [(D("406.15"), D("406.2")), (D("406.25"), D("406.3")), (D("15.045"), D("15.0"))],
)
def test_round_half_up(value, expected):
    assert round_to(value, ONE_DECIMAL) == expected
