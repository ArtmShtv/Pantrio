from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.db.models.catalog import ShopProduct
from app.db.models.enums import Unit
from app.schemas.common import Num
from app.services.calc import price_per_kg

ProductName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShopName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
PackSize = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class IngredientRef(BaseModel):
    id: int
    name: str


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingredient_id: int
    name: ProductName
    shop_name: ShopName
    pack_size: PackSize
    pack_unit: Unit
    price: Price


class ProductUpdate(BaseModel):
    """ingredient_id can't change: a pack of milk doesn't become a pack of rice.
    Delete and create a new product instead."""

    model_config = ConfigDict(extra="forbid")

    name: ProductName | None = None
    shop_name: ShopName | None = None
    pack_size: PackSize | None = None
    pack_unit: Unit | None = None
    price: Price | None = None

    @model_validator(mode="after")
    def check(self) -> Self:
        sent = self.model_fields_set
        for field in sent:
            if getattr(self, field) is None:
                raise ValueError(f"{field} can't be null")
        # "930" alone is ambiguous: 930 of what? Require both or neither.
        if ("pack_size" in sent) != ("pack_unit" in sent):
            raise ValueError("pack_size and pack_unit must be sent together")
        return self


class ProductRead(BaseModel):
    id: int
    ingredient_id: int
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
            ingredient_id=p.ingredient_id,
            name=p.name,
            shop_name=p.shop_name,
            pack_size_g=p.pack_size_g,
            price=p.price,
            price_per_kg=price_per_kg(p.price, p.pack_size_g),
            is_global=p.created_by_id is None,
        )
