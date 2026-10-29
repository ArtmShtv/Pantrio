"""Meals (recipes) and their ingredient lines."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, created_at, int_pk, updated_at
from app.db.models.catalog import Grams, Ingredient
from app.db.models.enums import Unit, str_enum


class Meal(Base):
    id: Mapped[int_pk]
    name: Mapped[str] = mapped_column(String(150))
    # NULL = global meal, same rule as Ingredient.
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # How many servings the recipe quantities make. PlanSlot.servings scales
    # from this: slot grams = item grams * slot.servings / meal.servings.
    servings: Mapped[int]

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    items: Mapped[list["RecipeItem"]] = relationship(
        back_populates="meal",
        lazy="raise",
        cascade="all, delete-orphan",  # removing an item from meal.items deletes the row
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("created_by_id", "name", postgresql_nulls_not_distinct=True),
        CheckConstraint("servings > 0", name="servings_positive"),
    )

    def __repr__(self) -> str:
        return f"Meal(id={self.id!r}, name={self.name!r})"


class RecipeItem(Base):
    id: Mapped[int_pk]
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id", ondelete="CASCADE"), index=True)
    # RESTRICT: an ingredient used in a recipe can't be deleted out from under it.
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"), index=True
    )
    # Kept in the unit the user entered ("2 pieces"), converted to grams when
    # calculating. Storing grams only would lose what the user typed.
    quantity: Mapped[Decimal] = mapped_column(Grams)
    unit: Mapped[Unit] = mapped_column(str_enum(Unit, "unit"))

    meal: Mapped[Meal] = relationship(back_populates="items", lazy="raise")
    ingredient: Mapped[Ingredient] = relationship(lazy="raise")

    __table_args__ = (
        # One line per ingredient; "100 g rice" + "50 g rice" should be "150 g rice".
        UniqueConstraint("meal_id", "ingredient_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )
