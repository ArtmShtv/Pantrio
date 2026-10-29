from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.enums import MealType
from app.schemas.common import Num
from app.schemas.meals import NutritionRead

Day = Annotated[int, Field(ge=0, le=6, description="0 = Monday ... 6 = Sunday")]
Servings = Annotated[Decimal, Field(gt=0, max_digits=5, decimal_places=2)]


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date

    @field_validator("start_date")
    @classmethod
    def must_be_monday(cls, v: date) -> date:
        if v.weekday() != 0:
            monday = v - timedelta(days=v.weekday())
            raise ValueError(f"must be a Monday; did you mean {monday.isoformat()}?")
        return v


class PlanListItem(BaseModel):
    id: int
    start_date: date
    slot_count: int


class MealRef(BaseModel):
    id: int
    name: str


class SlotRead(NutritionRead):
    id: int
    day: int
    meal_type: MealType
    meal: MealRef
    servings: Num
    cooked_at: datetime | None


class DayRead(BaseModel):
    day: int
    date: date
    slots: list[SlotRead]
    total: NutritionRead


class PlanDetail(BaseModel):
    id: int
    start_date: date
    days: list[DayRead]
    week_total: NutritionRead
    daily_average: NutritionRead


class SlotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Day
    meal_type: MealType
    meal_id: int
    servings: Servings | None = Field(None, description="Defaults to the meal's own servings")


class SlotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Day | None = None
    meal_type: MealType | None = None
    meal_id: int | None = None
    servings: Servings | None = None

    @model_validator(mode="after")
    def no_nulls(self) -> Self:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} can't be null")
        return self
