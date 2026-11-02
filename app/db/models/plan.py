"""Weekly plans and the meal slots inside them."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, created_at, int_pk
from app.db.models.enums import MealType, str_enum
from app.db.models.meal import Meal


class WeekPlan(Base):
    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    start_date: Mapped[date]
    created_at: Mapped[created_at]

    slots: Mapped[list["PlanSlot"]] = relationship(
        back_populates="plan",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "start_date"),
        CheckConstraint("extract(isodow from start_date) = 1", name="starts_on_monday"),
    )


class PlanSlot(Base):
    id: Mapped[int_pk]
    plan_id: Mapped[int] = mapped_column(ForeignKey("week_plans.id", ondelete="CASCADE"))
    day: Mapped[int] = mapped_column(SmallInteger)
    meal_type: Mapped[MealType] = mapped_column(str_enum(MealType, "meal_type"))
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id", ondelete="RESTRICT"), index=True)
    servings: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    cooked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[WeekPlan] = relationship(back_populates="slots", lazy="raise")
    meal: Mapped[Meal] = relationship(lazy="raise")

    __table_args__ = (
        Index("ix_plan_slots_plan_id_day", "plan_id", "day"),
        CheckConstraint("day BETWEEN 0 AND 6", name="day_range"),
        CheckConstraint("servings > 0", name="servings_positive"),
    )
