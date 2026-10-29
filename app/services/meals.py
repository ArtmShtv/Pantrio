from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.db.errors import constraint_name
from app.db.models.catalog import Ingredient
from app.db.models.meal import Meal, RecipeItem
from app.db.models.plan import PlanSlot
from app.db.models.user import User
from app.schemas.ingredients import Scope
from app.schemas.meals import (
    MealDetail,
    MealListItem,
    MealWrite,
    NutritionRead,
    RecipeItemIn,
    RecipeItemRead,
)
from app.schemas.products import IngredientRef
from app.services import ingredients as ingredients_service
from app.services.calc import (
    ONE_DECIMAL,
    Nutrition,
    UnitNotSupportedError,
    nutrition_for,
    round_to,
    to_grams,
    total,
)

# Every read needs items and their ingredients; the relationships are lazy="raise".
WITH_ITEMS = selectinload(Meal.items).selectinload(RecipeItem.ingredient)


def visible_to(user: User) -> ColumnElement[bool]:
    return or_(Meal.created_by_id.is_(None), Meal.created_by_id == user.id)


def _scope_filter(user: User, scope: Scope) -> ColumnElement[bool]:
    match scope:
        case Scope.MINE:
            return Meal.created_by_id == user.id
        case Scope.GLOBAL:
            return Meal.created_by_id.is_(None)
        case _:
            return visible_to(user)


def item_nutrition(item: RecipeItem) -> Nutrition:
    ing = item.ingredient
    grams = to_grams(
        item.quantity, item.unit, grams_per_piece=ing.grams_per_piece, grams_per_ml=ing.grams_per_ml
    )
    return nutrition_for(
        grams, calories=ing.calories, protein=ing.protein, fat=ing.fat, carbs=ing.carbs
    )


def meal_total(meal: Meal) -> Nutrition:
    return total(item_nutrition(i) for i in meal.items)


def to_list_item(meal: Meal) -> MealListItem:
    kcal = meal_total(meal).kcal / meal.servings
    return MealListItem(
        id=meal.id,
        name=meal.name,
        servings=meal.servings,
        is_global=meal.created_by_id is None,
        kcal_per_serving=round_to(kcal, ONE_DECIMAL),
    )


def to_detail(meal: Meal) -> MealDetail:
    items = sorted(meal.items, key=lambda i: i.id)
    parts = [item_nutrition(i) for i in items]
    meal_sum = total(parts)
    return MealDetail(
        id=meal.id,
        name=meal.name,
        servings=meal.servings,
        is_global=meal.created_by_id is None,
        items=[
            RecipeItemRead(
                id=item.id,
                ingredient=IngredientRef(id=item.ingredient.id, name=item.ingredient.name),
                quantity=item.quantity,
                unit=item.unit,
                **NutritionRead.from_calc(n).model_dump(),
            )
            for item, n in zip(items, parts, strict=True)
        ],
        total=NutritionRead.from_calc(meal_sum),
        per_serving=NutritionRead.from_calc(meal_sum.scale(Decimal(1) / meal.servings)),
    )




async def list_meals(
    session: AsyncSession, user: User, *, q: str | None, scope: Scope, limit: int, offset: int
) -> tuple[Sequence[Meal], int]:
    conditions = [_scope_filter(user, scope)]
    if q:
        conditions.append(Meal.name.icontains(q, autoescape=True))
    total_count = await session.scalar(select(func.count()).select_from(Meal).where(*conditions))
    rows = await session.scalars(
        select(Meal)
        .options(WITH_ITEMS)
        .where(*conditions)
        .order_by(func.lower(Meal.name), Meal.id)
        .limit(limit)
        .offset(offset)
    )
    return rows.all(), total_count or 0


async def get_visible(session: AsyncSession, user: User, meal_id: int) -> Meal:
    meal = await session.scalar(
        select(Meal).options(WITH_ITEMS).where(Meal.id == meal_id, visible_to(user))
    )
    if meal is None:
        raise NotFoundError("Meal not found")
    return meal




def _ensure_can_edit(user: User, meal: Meal) -> None:
    if meal.created_by_id is None and not user.is_admin:
        raise PermissionDeniedError("Only admins can change global meals")


async def _ensure_name_free(
    session: AsyncSession, owner_id: int | None, name: str, exclude_id: int | None = None
) -> None:
    owner = Meal.created_by_id.is_(None) if owner_id is None else Meal.created_by_id == owner_id
    stmt = select(Meal.id).where(owner, func.lower(Meal.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Meal.id != exclude_id)
    if await session.scalar(stmt.limit(1)) is not None:
        raise ConflictError(f"A meal named {name!r} already exists")


async def _build_items(
    session: AsyncSession, user: User, items: list[RecipeItemIn], *, is_global: bool
) -> list[RecipeItem]:
    """Validate the lines and turn them into RecipeItem rows (not yet added)."""
    ids = [i.ingredient_id for i in items]
    found = {
        ing.id: ing
        for ing in await session.scalars(
            select(Ingredient).where(Ingredient.id.in_(ids), ingredients_service.visible_to(user))
        )
    }
    if missing := [i for i in ids if i not in found]:
        # Unknown and invisible look the same on purpose: no existence leak.
        raise DomainValidationError(f"Unknown ingredient id(s): {missing}")

    rows = []
    for line in items:
        ing = found[line.ingredient_id]
        if is_global and ing.created_by_id is not None:
            raise DomainValidationError(
                f"A global meal can only use global ingredients; {ing.name!r} is private"
            )
        try:
            to_grams(
                line.quantity,
                line.unit,
                grams_per_piece=ing.grams_per_piece,
                grams_per_ml=ing.grams_per_ml,
            )
        except UnitNotSupportedError as e:
            raise DomainValidationError(f"{ing.name!r}: {e}") from None
        # Assigning the relationship (not just ingredient_id) keeps item.ingredient
        # loaded, so the response can be built without another query.
        rows.append(RecipeItem(ingredient=ing, quantity=line.quantity, unit=line.unit))
    return rows


async def create_meal(
    session: AsyncSession, user: User, data: MealWrite, *, make_global: bool
) -> Meal:
    if make_global and not user.is_admin:
        raise PermissionDeniedError("Only admins can create global meals")
    owner_id = None if make_global else user.id
    await _ensure_name_free(session, owner_id, data.name)

    meal = Meal(name=data.name, servings=data.servings, created_by_id=owner_id)
    meal.items = await _build_items(session, user, data.items, is_global=make_global)
    session.add(meal)
    await _commit_or_conflict(session, data.name)
    return meal


async def replace_meal(session: AsyncSession, user: User, meal_id: int, data: MealWrite) -> Meal:
    meal = await get_visible(session, user, meal_id)
    _ensure_can_edit(user, meal)
    await _ensure_name_free(session, meal.created_by_id, data.name, exclude_id=meal.id)
    new_items = await _build_items(session, user, data.items, is_global=meal.created_by_id is None)

    meal.name = data.name
    meal.servings = data.servings
    # Delete the old lines *before* inserting the new ones. In one flush,
    # SQLAlchemy inserts before it deletes, so keeping an ingredient (rice ->
    # rice with a new quantity) would hit UNIQUE (meal_id, ingredient_id).
    meal.items.clear()
    await session.flush()
    meal.items.extend(new_items)
    await _commit_or_conflict(session, data.name)
    return meal


async def delete_meal(session: AsyncSession, user: User, meal_id: int) -> None:
    meal = await get_visible(session, user, meal_id)
    _ensure_can_edit(user, meal)

    used = await session.scalar(select(func.count()).where(PlanSlot.meal_id == meal.id))
    if used:
        raise ConflictError(f"Meal is used in {used} plan slot(s); remove it from plans first")

    await session.delete(meal)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Meal is used in a plan") from None


async def _commit_or_conflict(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        # Only the name constraint means "name taken"; anything else is a bug
        # and should surface as a 500, not as a misleading 409.
        if constraint_name(e) == "uq_meals_created_by_id_name":
            raise ConflictError(f"A meal named {name!r} already exists") from None
        raise
