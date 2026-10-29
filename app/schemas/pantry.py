from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import Unit
from app.schemas.common import Num
from app.schemas.plans import SlotRead
from app.schemas.products import IngredientRef


class PantryItemRead(BaseModel):
    ingredient: IngredientRef
    quantity_g: Num
    updated_at: datetime


class PantrySet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
    unit: Unit = Unit.G


class PurchaseLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: int
    quantity: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
    unit: Unit = Unit.G


class Purchase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[PurchaseLine], Field(min_length=1, max_length=200)]


class PantryChange(BaseModel):
    ingredient: IngredientRef
    before_g: Num
    after_g: Num


class CookResult(BaseModel):
    slot: SlotRead
    pantry_changes: list[PantryChange]
