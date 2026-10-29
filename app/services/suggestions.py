"""Meal suggestions: rank meals by how much of them the pantry already covers.

`score` and `rank` are pure; `suggest` loads the data and calls them.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.catalog import Ingredient, ShopProduct
from app.db.models.meal import Meal, RecipeItem
from app.db.models.pantry import Leftover
from app.db.models.user import User
from app.services import meals as meals_service
from app.services import products as products_service
from app.services.calc import to_grams


class Strategy(StrEnum):
    SHARE = "share"
    GRAMS = "grams"
    MONEY = "money"


@dataclass(frozen=True)
class LineIn:
    ingredient: Ingredient
    need_g: Decimal
    have_g: Decimal  # already capped: min(pantry, need)
    price_per_g: Decimal | None


@dataclass(frozen=True)
class Suggestion:
    meal: Meal
    score: Decimal
    lines: list[LineIn]


def score(lines: list[LineIn], strategy: Strategy) -> Decimal:
    if not lines:
        return Decimal(0)
    match strategy:
        case Strategy.SHARE:
            return sum((ln.have_g / ln.need_g for ln in lines), Decimal(0)) / len(lines)
        case Strategy.GRAMS:
            return sum(ln.have_g for ln in lines) / sum(ln.need_g for ln in lines)
        case Strategy.MONEY:
            priced = [ln for ln in lines if ln.price_per_g is not None]
            value = sum((ln.need_g * ln.price_per_g for ln in priced), Decimal(0))
            if value == 0:
                return Decimal(0)
            return sum(ln.have_g * ln.price_per_g for ln in priced) / value


def rank(
    candidates: list[tuple[Meal, list[LineIn]]], strategy: Strategy, limit: int
) -> list[Suggestion]:
    scored = [Suggestion(meal, score(lines, strategy), lines) for meal, lines in candidates]
    scored = [s for s in scored if s.score > 0]
    scored.sort(key=lambda s: (-s.score, s.meal.name.lower(), s.meal.id))
    return scored[:limit]


def meal_lines(meal: Meal, pantry: dict[int, Decimal], prices: dict[int, Decimal]) -> list[LineIn]:
    """Grams per ingredient for one batch of the recipe (its own servings)."""
    lines = []
    for item in meal.items:
        ing = item.ingredient
        need = to_grams(
            item.quantity,
            item.unit,
            grams_per_piece=ing.grams_per_piece,
            grams_per_ml=ing.grams_per_ml,
        )
        lines.append(
            LineIn(ing, need, min(pantry.get(ing.id, Decimal(0)), need), prices.get(ing.id))
        )
    return lines


async def _price_per_gram(
    session: AsyncSession, user: User, ingredient_ids: set[int]
) -> dict[int, Decimal]:
    """Lowest price per gram per ingredient, own products first (same rule as the shopping list)."""
    own: dict[int, list[Decimal]] = defaultdict(list)
    other: dict[int, list[Decimal]] = defaultdict(list)
    for p in await session.scalars(
        select(ShopProduct).where(
            ShopProduct.ingredient_id.in_(ingredient_ids), products_service.visible_to(user)
        )
    ):
        (own if p.created_by_id == user.id else other)[p.ingredient_id].append(
            p.price / p.pack_size_g
        )
    return {i: min(own.get(i) or other[i]) for i in own.keys() | other.keys()}


async def suggest(
    session: AsyncSession, user: User, *, strategy: Strategy, limit: int
) -> list[Suggestion]:
    pantry = {
        ing_id: grams
        for ing_id, grams in await session.execute(
            select(Leftover.ingredient_id, Leftover.quantity_g).where(Leftover.user_id == user.id)
        )
    }
    if not pantry:
        return []

    # Only meals that use at least one pantry ingredient can score above 0.
    uses_pantry = (
        select(RecipeItem.meal_id).where(RecipeItem.ingredient_id.in_(pantry)).scalar_subquery()
    )
    meals = (
        await session.scalars(
            select(Meal)
            .options(meals_service.WITH_ITEMS)
            .where(meals_service.visible_to(user), Meal.id.in_(uses_pantry))
        )
    ).all()

    prices: dict[int, Decimal] = {}
    if strategy == Strategy.MONEY and meals:
        ids = {item.ingredient_id for m in meals for item in m.items}
        prices = await _price_per_gram(session, user, ids)

    candidates = [(m, meal_lines(m, pantry, prices)) for m in meals]
    return rank(candidates, strategy, limit)
