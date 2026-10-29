from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.db.models.catalog import Ingredient, ShopProduct
from app.schemas.common import Num


class Scope(StrEnum):
    ALL = "all"
    MINE = "mine"
    GLOBAL = "global"


class CreateScope(StrEnum):
    PRIVATE = "private"
    GLOBAL = "global"


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Limits match the DB column types, so bad input is a 422 here, not a DB error.
# decimal_places rejects 12.345 instead of the DB silently rounding it.
Kcal = Annotated[Decimal, Field(ge=0, le=900, max_digits=6, decimal_places=2)]
Macro = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
GramsPerPiece = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
GramsPerMl = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=4)]

_MACROS_ERROR = "protein + fat + carbs can't exceed 100 g per 100 g"


class IngredientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    calories: Kcal
    protein: Macro
    fat: Macro
    carbs: Macro
    grams_per_piece: GramsPerPiece | None = None
    grams_per_ml: GramsPerMl | None = None

    @model_validator(mode="after")
    def macros_fit(self) -> Self:
        if self.protein + self.fat + self.carbs > 100:
            raise ValueError(_MACROS_ERROR)
        return self


class IngredientUpdate(BaseModel):
    """Partial update. The macro sum is checked in the service, after merging
    with the stored values: a PATCH may send only `fat`."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    calories: Kcal | None = None
    protein: Macro | None = None
    fat: Macro | None = None
    carbs: Macro | None = None
    # null is allowed here: it means "can't be measured in pieces/ml any more".
    grams_per_piece: GramsPerPiece | None = None
    grams_per_ml: GramsPerMl | None = None

    @field_validator("name", "calories", "protein", "fat", "carbs")
    @classmethod
    def not_null(cls, v: object) -> object:
        # Runs only for fields that were sent, so an omitted field is fine.
        if v is None:
            raise ValueError("can't be null")
        return v


class IngredientRead(BaseModel):
    id: int
    name: str
    is_global: bool
    calories: Num
    protein: Num
    fat: Num
    carbs: Num
    grams_per_piece: Num | None
    grams_per_ml: Num | None

    @classmethod
    def from_model(cls, ing: Ingredient) -> Self:
        return cls(
            id=ing.id,
            name=ing.name,
            is_global=ing.created_by_id is None,
            calories=ing.calories,
            protein=ing.protein,
            fat=ing.fat,
            carbs=ing.carbs,
            grams_per_piece=ing.grams_per_piece,
            grams_per_ml=ing.grams_per_ml,
        )


class ProductRead(BaseModel):
    id: int
    name: str
    shop_name: str
    pack_size_g: Num
    price: Num
    price_per_kg: Num
    is_global: bool

    @classmethod
    def from_model(cls, p: ShopProduct) -> Self:
        return cls(
            id=p.id,
            name=p.name,
            shop_name=p.shop_name,
            pack_size_g=p.pack_size_g,
            price=p.price,
            price_per_kg=(p.price / p.pack_size_g * 1000).quantize(Decimal("0.01")),
            is_global=p.created_by_id is None,
        )


class IngredientDetail(IngredientRead):
    products: list[ProductRead]
