from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, created_at, int_pk, updated_at

Grams = Numeric(10, 2)
Per100g = Numeric(6, 2)
Money = Numeric(10, 2)


class Ingredient(Base):
    id: Mapped[int_pk]
    name: Mapped[str] = mapped_column(String(100))
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    calories: Mapped[Decimal] = mapped_column(Per100g)
    protein: Mapped[Decimal] = mapped_column(Per100g)
    fat: Mapped[Decimal] = mapped_column(Per100g)
    carbs: Mapped[Decimal] = mapped_column(Per100g)

    grams_per_piece: Mapped[Decimal | None] = mapped_column(Grams)
    grams_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    shop_products: Mapped[list["ShopProduct"]] = relationship(
        back_populates="ingredient", lazy="raise", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("created_by_id", "name", postgresql_nulls_not_distinct=True),
        CheckConstraint(
            "calories >= 0 AND protein >= 0 AND fat >= 0 AND carbs >= 0",
            name="nutrition_non_negative",
        ),
        CheckConstraint("protein + fat + carbs <= 100", name="macros_max_100"),
        CheckConstraint("grams_per_piece IS NULL OR grams_per_piece > 0", name="grams_per_piece"),
        CheckConstraint("grams_per_ml IS NULL OR grams_per_ml > 0", name="grams_per_ml"),
    )

    def __repr__(self) -> str:
        return f"Ingredient(id={self.id!r}, name={self.name!r})"


class ShopProduct(Base):
    id: Mapped[int_pk]
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    shop_name: Mapped[str] = mapped_column(String(100))
    pack_size_g: Mapped[Decimal] = mapped_column(Grams)
    price: Mapped[Decimal] = mapped_column(Money)

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    ingredient: Mapped[Ingredient] = relationship(back_populates="shop_products", lazy="raise")

    __table_args__ = (
        CheckConstraint("pack_size_g > 0", name="pack_size_positive"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )
