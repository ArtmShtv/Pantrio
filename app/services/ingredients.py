from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.db.models.catalog import Ingredient
from app.db.models.enums import Unit
from app.db.models.meal import Meal, RecipeItem
from app.db.models.user import User
from app.schemas.ingredients import IngredientCreate, Scope


def visible_to(user: User) -> ColumnElement[bool]:
    return or_(Ingredient.created_by_id.is_(None), Ingredient.created_by_id == user.id)


def _scope_filter(user: User, scope: Scope) -> ColumnElement[bool]:
    match scope:
        case Scope.MINE:
            return Ingredient.created_by_id == user.id
        case Scope.GLOBAL:
            return Ingredient.created_by_id.is_(None)
        case _:
            return visible_to(user)


async def list_ingredients(
    session: AsyncSession, user: User, *, q: str | None, scope: Scope, limit: int, offset: int
) -> tuple[Sequence[Ingredient], int]:
    conditions = [_scope_filter(user, scope)]
    if q:
        # autoescape: a search for "100%" matches a literal "%", not "anything".
        conditions.append(Ingredient.name.icontains(q, autoescape=True))

    total = await session.scalar(select(func.count()).select_from(Ingredient).where(*conditions))
    rows = await session.scalars(
        select(Ingredient)
        .where(*conditions)
        .order_by(func.lower(Ingredient.name), Ingredient.id)
        .limit(limit)
        .offset(offset)
    )
    return rows.all(), total or 0


async def get_visible(session: AsyncSession, user: User, ingredient_id: int) -> Ingredient:
    ing = await session.scalar(
        select(Ingredient).where(Ingredient.id == ingredient_id, visible_to(user))
    )
    if ing is None:
        raise NotFoundError("Ingredient not found")
    return ing


def _ensure_can_edit(user: User, ing: Ingredient) -> None:
    # Other users' private rows never get here: get_visible already 404'd.
    if ing.created_by_id is None and not user.is_admin:
        raise PermissionDeniedError("Only admins can change global ingredients")


async def _ensure_name_free(
    session: AsyncSession, owner_id: int | None, name: str, exclude_id: int | None = None
) -> None:
    # Case-insensitive on purpose: "Rice" and "rice" in one list is a mistake.
    # The DB unique constraint is case-sensitive, so it can't catch this.
    owner = (
        Ingredient.created_by_id.is_(None)
        if owner_id is None
        else Ingredient.created_by_id == owner_id
    )
    stmt = select(Ingredient.id).where(owner, func.lower(Ingredient.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Ingredient.id != exclude_id)
    if await session.scalar(stmt.limit(1)) is not None:
        raise ConflictError(f"An ingredient named {name!r} already exists")


async def _meals_using(
    session: AsyncSession, ingredient_id: int, unit: Unit | None = None
) -> list[str]:
    """Names of meals that use the ingredient (optionally in a given unit).

    Showing names is safe: only the owner (private) or an admin (global) gets
    here, and a private ingredient can only be used by its owner's meals.
    """
    stmt = (
        select(Meal.name)
        .join(RecipeItem, RecipeItem.meal_id == Meal.id)
        .where(RecipeItem.ingredient_id == ingredient_id)
        .order_by(Meal.name)
    )
    if unit is not None:
        stmt = stmt.where(RecipeItem.unit == unit)
    return list(await session.scalars(stmt))


def _describe(names: list[str]) -> str:
    shown = ", ".join(repr(n) for n in names[:5])
    more = len(names) - 5
    return f"{shown} and {more} more" if more > 0 else shown


async def create_ingredient(
    session: AsyncSession, user: User, data: IngredientCreate, *, make_global: bool
) -> Ingredient:
    if make_global and not user.is_admin:
        raise PermissionDeniedError("Only admins can create global ingredients")
    owner_id = None if make_global else user.id
    await _ensure_name_free(session, owner_id, data.name)

    ing = Ingredient(created_by_id=owner_id, **data.model_dump())
    session.add(ing)
    await _commit_or_conflict(session, data.name)
    return ing


async def update_ingredient(
    session: AsyncSession, user: User, ingredient_id: int, changes: dict[str, Any]
) -> Ingredient:
    ing = await get_visible(session, user, ingredient_id)
    _ensure_can_edit(user, ing)

    if "name" in changes:
        await _ensure_name_free(session, ing.created_by_id, changes["name"], exclude_id=ing.id)

    for field, unit in (("grams_per_piece", Unit.PIECE), ("grams_per_ml", Unit.ML)):
        if field in changes and changes[field] is None and getattr(ing, field) is not None:
            if names := await _meals_using(session, ing.id, unit):
                raise ConflictError(
                    f"Can't remove {field}: used in {unit.value} by {_describe(names)}"
                )

    protein = changes.get("protein", ing.protein)
    fat = changes.get("fat", ing.fat)
    carbs = changes.get("carbs", ing.carbs)
    if protein + fat + carbs > 100:
        raise DomainValidationError("protein + fat + carbs can't exceed 100 g per 100 g")

    for field, value in changes.items():
        setattr(ing, field, value)
    await _commit_or_conflict(session, ing.name)
    return ing


async def delete_ingredient(session: AsyncSession, user: User, ingredient_id: int) -> None:
    ing = await get_visible(session, user, ingredient_id)
    _ensure_can_edit(user, ing)

    if names := await _meals_using(session, ing.id):
        raise ConflictError(f"Ingredient is used by {_describe(names)}")

    await session.delete(ing)
    try:
        await session.commit()
    except IntegrityError:
        # A recipe started using it between our check and the delete (FK RESTRICT).
        await session.rollback()
        raise ConflictError("Ingredient is used by a meal") from None


async def _commit_or_conflict(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError:
        # Two requests created the same name at once; the unique constraint caught it.
        await session.rollback()
        raise ConflictError(f"An ingredient named {name!r} already exists") from None
