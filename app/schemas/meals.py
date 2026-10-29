from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.db.models.enums import Unit
from app.schemas.common import Num
from app.schemas.products import IngredientRef
from app.services.calc import ONE_DECIMAL, Nutrition, round_to

MealName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


class RecipeItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: int
    quantity: Quantity
    unit: Unit


class MealWrite(BaseModel):
    """Body of POST and PUT: the whole meal, items included."""

    model_config = ConfigDict(extra="forbid")

    name: MealName
    servings: Annotated[int, Field(ge=1, le=100)]
    items: Annotated[list[RecipeItemIn], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def no_duplicate_ingredients(self) -> Self:
        seen: set[int] = set()
        for item in self.items:
            if item.ingredient_id in seen:
                raise ValueError(
                    f"ingredient {item.ingredient_id} is listed twice; merge the lines"
                )
            seen.add(item.ingredient_id)
        return self


class NutritionRead(BaseModel):
    grams: Num
    kcal: Num
    protein: Num
    fat: Num
    carbs: Num

    @classmethod
    def from_calc(cls, n: Nutrition) -> Self:
        return cls(
            grams=round_to(n.grams, ONE_DECIMAL),
            kcal=round_to(n.kcal, ONE_DECIMAL),
            protein=round_to(n.protein, ONE_DECIMAL),
            fat=round_to(n.fat, ONE_DECIMAL),
            carbs=round_to(n.carbs, ONE_DECIMAL),
        )


class RecipeItemRead(NutritionRead):
    id: int
    ingredient: IngredientRef
    quantity: Num
    unit: Unit


class MealListItem(BaseModel):
    id: int
    name: str
    servings: int
    is_global: bool
    kcal_per_serving: Num


class MealDetail(BaseModel):
    id: int
    name: str
    servings: int
    is_global: bool
    items: list[RecipeItemRead]
    total: NutritionRead
    per_serving: NutritionRead
