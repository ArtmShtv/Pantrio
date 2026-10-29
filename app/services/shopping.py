"""Shopping list for a week plan.

Pure functions (needs_from_slots, choose_pack, build_line) do the maths and
are tested without a database. build_shopping_list is the one loader.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.catalog import Ingredient, ShopProduct
from app.db.models.pantry import Leftover
from app.db.models.plan import PlanSlot
from app.db.models.user import User
from app.services import plans as plans_service
from app.services import products as products_service
from app.services.calc import GRAMS, round_to, to_grams


@dataclass(frozen=True)
class Pack:
    id: int
    name: str
    shop_name: str
    pack_size_g: Decimal
    price: Decimal
    is_own: bool


@dataclass(frozen=True)
class Line:
    ingredient_id: int
    need_g: Decimal
    in_pantry_g: Decimal
    to_buy_g: Decimal
    pack: Pack | None
    packs: int | None
    cost: Decimal | None
    surplus_g: Decimal | None


# --- pure maths --------------------------------------------------------------


def needs_from_slots(slots: Iterable[PlanSlot]) -> dict[int, Decimal]:
    """Grams needed per ingredient id, over the uncooked slots.

    Rounded to 0.01 g: dividing by servings leaves repeating-decimal tails.
    100 g eaten as 1.5 + 2 + 2 + 2 of 3 servings sums to
    250.0000000000000000000000001 g, and ceil() would buy a second 250 g pack.
    """
    need: dict[int, Decimal] = defaultdict(Decimal)
    for slot in slots:
        if slot.cooked_at is not None:
            continue
        factor = slot.servings / slot.meal.servings
        for item in slot.meal.items:
            ing = item.ingredient
            grams = to_grams(
                item.quantity,
                item.unit,
                grams_per_piece=ing.grams_per_piece,
                grams_per_ml=ing.grams_per_ml,
            )
            need[ing.id] += grams * factor
    return {ing_id: round_to(g, GRAMS) for ing_id, g in need.items()}


def packs_needed(to_buy_g: Decimal, pack_size_g: Decimal) -> int:
    return int((to_buy_g / pack_size_g).to_integral_value(rounding=ROUND_CEILING))


def choose_pack(to_buy_g: Decimal, candidates: Sequence[Pack]) -> Pack | None:
    """The user's own products if they have any, else global ones.
    Among those: the lowest cost for this amount, then the least left over."""
    own = [p for p in candidates if p.is_own]
    pool = own or list(candidates)
    if not pool:
        return None

    def key(p: Pack) -> tuple[Decimal, Decimal, int]:
        n = packs_needed(to_buy_g, p.pack_size_g)
        return (n * p.price, n * p.pack_size_g - to_buy_g, p.id)

    return min(pool, key=key)


def build_line(
    ingredient_id: int,
    need_g: Decimal,
    pantry_g: Decimal,
    candidates: Sequence[Pack],
    *,
    use_pantry: bool,
) -> Line | None:
    """None when nothing needs buying (the pantry covers it)."""
    to_buy = max(Decimal(0), need_g - pantry_g) if use_pantry else need_g
    if to_buy == 0:
        return None
    pack = choose_pack(to_buy, candidates)
    if pack is None:
        return Line(ingredient_id, need_g, pantry_g, to_buy, None, None, None, None)
    n = packs_needed(to_buy, pack.pack_size_g)
    return Line(
        ingredient_id,
        need_g,
        pantry_g,
        to_buy,
        pack,
        n,
        n * pack.price,
        n * pack.pack_size_g - to_buy,
    )


# --- loader ------------------------------------------------------------------


@dataclass(frozen=True)
class ShoppingList:
    plan_id: int
    use_pantry: bool
    lines: list[tuple[Line, Ingredient]]
    total_cost: Decimal
    missing_prices: list[Ingredient]


async def build_shopping_list(
    session: AsyncSession, user: User, plan_id: int, *, use_pantry: bool
) -> ShoppingList:
    plan = await plans_service.get_plan(session, user, plan_id)
    need = needs_from_slots(plan.slots)
    ingredients = {
        item.ingredient.id: item.ingredient for slot in plan.slots for item in slot.meal.items
    }
    ids = list(need)

    candidates: dict[int, list[Pack]] = defaultdict(list)
    if ids:
        for p in await session.scalars(
            select(ShopProduct).where(
                ShopProduct.ingredient_id.in_(ids), products_service.visible_to(user)
            )
        ):
            candidates[p.ingredient_id].append(
                Pack(p.id, p.name, p.shop_name, p.pack_size_g, p.price, p.created_by_id == user.id)
            )

    pantry: dict[int, Decimal] = {}
    if ids:
        rows = await session.execute(
            select(Leftover.ingredient_id, Leftover.quantity_g).where(
                Leftover.user_id == user.id, Leftover.ingredient_id.in_(ids)
            )
        )
        pantry = {ing_id: grams for ing_id, grams in rows}

    lines = []
    for ing_id in sorted(ids, key=lambda i: (ingredients[i].name.lower(), i)):
        line = build_line(
            ing_id,
            need[ing_id],
            pantry.get(ing_id, Decimal(0)),
            candidates[ing_id],
            use_pantry=use_pantry,
        )
        if line is not None:
            lines.append((line, ingredients[ing_id]))

    return ShoppingList(
        plan_id=plan.id,
        use_pantry=use_pantry,
        lines=lines,
        total_cost=sum((ln.cost for ln, _ in lines if ln.cost is not None), Decimal(0)),
        missing_prices=[ing for ln, ing in lines if ln.pack is None],
    )
