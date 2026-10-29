"""Pantry: raw ingredients the user has at home."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, int_pk, updated_at
from app.db.models.catalog import Grams, Ingredient


class Leftover(Base):
    """How much of an ingredient the user has, in grams.

    Grows when a shopping list is marked as bought (pack surplus), shrinks
    when a plan slot is marked as cooked. When the quantity reaches 0,
    delete the row instead of keeping a zero. The CHECK enforces this.
    """

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), index=True
    )
    quantity_g: Mapped[Decimal] = mapped_column(Grams)
    updated_at: Mapped[updated_at]

    ingredient: Mapped[Ingredient] = relationship(lazy="raise")

    __table_args__ = (
        # Makes INSERT ... ON CONFLICT (user_id, ingredient_id) DO UPDATE
        # possible: add to the existing amount atomically, no read-then-write race.
        UniqueConstraint("user_id", "ingredient_id"),
        CheckConstraint("quantity_g > 0", name="quantity_positive"),
    )
