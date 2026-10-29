from typing import Self

from pydantic import BaseModel

from app.schemas.common import Num
from app.schemas.products import IngredientRef
from app.services.calc import MONEY, ONE_DECIMAL, round_to
from app.services.shopping import ShoppingList


class ShoppingProduct(BaseModel):
    id: int
    name: str
    shop_name: str
    pack_size_g: Num
    price: Num


class ShoppingLine(BaseModel):
    ingredient: IngredientRef
    need_g: Num
    in_pantry_g: Num
    to_buy_g: Num
    product: ShoppingProduct | None
    packs: int | None
    cost: Num | None
    surplus_g: Num | None


class ShoppingListRead(BaseModel):
    plan_id: int
    use_pantry: bool
    lines: list[ShoppingLine]
    total_cost: Num
    missing_prices: list[IngredientRef]

    @classmethod
    def from_service(cls, s: ShoppingList) -> Self:
        def g(v):
            return None if v is None else round_to(v, ONE_DECIMAL)

        lines = []
        for ln, ing in s.lines:
            p = ln.pack
            lines.append(
                ShoppingLine(
                    ingredient=IngredientRef(id=ing.id, name=ing.name),
                    need_g=g(ln.need_g),
                    in_pantry_g=g(ln.in_pantry_g),
                    to_buy_g=g(ln.to_buy_g),
                    product=None
                    if p is None
                    else ShoppingProduct(
                        id=p.id,
                        name=p.name,
                        shop_name=p.shop_name,
                        pack_size_g=p.pack_size_g,
                        price=p.price,
                    ),
                    packs=ln.packs,
                    cost=None if ln.cost is None else round_to(ln.cost, MONEY),
                    surplus_g=g(ln.surplus_g),
                )
            )
        return cls(
            plan_id=s.plan_id,
            use_pantry=s.use_pantry,
            lines=lines,
            total_cost=round_to(s.total_cost, MONEY),
            missing_prices=[IngredientRef(id=i.id, name=i.name) for i in s.missing_prices],
        )
