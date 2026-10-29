"""The pantry: grams of each raw ingredient the user has at home.

Writes that add to an amount use one atomic INSERT ... ON CONFLICT DO UPDATE
(quantity_g = quantity_g + excluded.quantity_g). Reading the row, adding in
Python and writing it back would lose an update when two requests run at
once: both read 100, both write 100 + theirs.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.core.exceptions import DomainValidationError
from app.db.models.catalog import Ingredient
from app.db.models.enums import Unit
from app.db.models.pantry import Leftover
from app.db.models.user import User
from app.schemas.pantry import PurchaseLine
from app.services import ingredients as ingredients_service
from app.services.calc import GRAMS, UnitNotSupportedError, round_to, to_grams


@dataclass(frozen=True)
class Change:
    ingredient_id: int
    before_g: Decimal
    after_g: Decimal


def grams_of(ing: Ingredient, quantity: Decimal, unit: Unit) -> Decimal:
    try:
        grams = to_grams(
            quantity, unit, grams_per_piece=ing.grams_per_piece, grams_per_ml=ing.grams_per_ml
        )
    except UnitNotSupportedError as e:
        raise DomainValidationError(f"{ing.name!r}: {e}") from None
    return round_to(grams, GRAMS)


async def list_pantry(session: AsyncSession, user: User) -> Sequence[Leftover]:
    rows = await session.scalars(
        select(Leftover)
        .join(Leftover.ingredient)
        .options(contains_eager(Leftover.ingredient))
        .where(Leftover.user_id == user.id)
        .order_by(func.lower(Ingredient.name), Ingredient.id)
        # The writes below bypass the ORM, so objects already in the session
        # may hold old amounts. populate_existing overwrites them with the DB values.
        .execution_options(populate_existing=True)
    )
    return rows.all()


async def get_item(session: AsyncSession, user: User, ingredient_id: int) -> Leftover | None:
    return await session.scalar(
        select(Leftover)
        .options(contains_eager(Leftover.ingredient))
        .join(Leftover.ingredient)
        .where(Leftover.user_id == user.id, Leftover.ingredient_id == ingredient_id)
        .execution_options(populate_existing=True)
    )


async def set_quantity(
    session: AsyncSession, user: User, ingredient_id: int, quantity: Decimal, unit: Unit
) -> Leftover | None:
    """Set (not add) the amount. Returns None when it was set to zero (row deleted)."""
    ing = await ingredients_service.get_visible(session, user, ingredient_id)
    grams = grams_of(ing, quantity, unit)
    if grams == 0:
        await _delete(session, user.id, ingredient_id)
        await session.commit()
        return None

    stmt = insert(Leftover).values(user_id=user.id, ingredient_id=ing.id, quantity_g=grams)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Leftover.user_id, Leftover.ingredient_id],
        # onupdate=func.now() on the model only fires for ORM updates; a Core
        # upsert has to set updated_at itself.
        set_={"quantity_g": stmt.excluded.quantity_g, "updated_at": func.now()},
    )
    await session.execute(stmt)
    await session.commit()
    return await get_item(session, user, ing.id)


async def delete_item(session: AsyncSession, user: User, ingredient_id: int) -> None:
    await _delete(session, user.id, ingredient_id)
    await session.commit()


async def _delete(session: AsyncSession, user_id: int, ingredient_id: int) -> None:
    await session.execute(
        delete(Leftover).where(Leftover.user_id == user_id, Leftover.ingredient_id == ingredient_id)
    )


async def add_grams(session: AsyncSession, user_id: int, amounts: dict[int, Decimal]) -> None:
    """Atomically add grams per ingredient id. Does not commit."""
    rows = [
        {"user_id": user_id, "ingredient_id": ing_id, "quantity_g": grams}
        for ing_id, grams in amounts.items()
        if grams > 0
    ]
    if not rows:
        return
    stmt = insert(Leftover).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Leftover.user_id, Leftover.ingredient_id],
        set_={
            "quantity_g": Leftover.quantity_g + stmt.excluded.quantity_g,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)


async def subtract_grams(
    session: AsyncSession, user_id: int, amounts: dict[int, Decimal]
) -> list[Change]:
    """Subtract grams per ingredient; an amount that would go below 0 stops at 0
    (the row is deleted). Locks the rows (FOR UPDATE) so a parallel purchase waits.
    Does not commit."""
    if not amounts:
        return []
    rows = {
        r.ingredient_id: r
        for r in await session.scalars(
            select(Leftover)
            .where(Leftover.user_id == user_id, Leftover.ingredient_id.in_(amounts))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    changes = []
    for ing_id, grams in sorted(amounts.items()):
        row = rows.get(ing_id)
        before = row.quantity_g if row else Decimal(0)
        after = max(Decimal(0), before - grams)
        if row is not None:
            if after == 0:
                await session.delete(row)
            else:
                row.quantity_g = after
        changes.append(Change(ing_id, before, after))
    return changes


async def record_purchase(
    session: AsyncSession, user: User, lines: Iterable[PurchaseLine]
) -> Sequence[Leftover]:
    lines = list(lines)
    ids = {ln.ingredient_id for ln in lines}
    found = {
        i.id: i
        for i in await session.scalars(
            select(Ingredient).where(Ingredient.id.in_(ids), ingredients_service.visible_to(user))
        )
    }
    if missing := sorted(ids - found.keys()):
        raise DomainValidationError(f"Unknown ingredient id(s): {missing}")

    # The same ingredient twice in one INSERT ... ON CONFLICT is an error in
    # Postgres ("cannot affect row a second time"), so merge the lines first.
    amounts: dict[int, Decimal] = defaultdict(Decimal)
    for ln in lines:
        amounts[ln.ingredient_id] += grams_of(found[ln.ingredient_id], ln.quantity, ln.unit)

    await add_grams(session, user.id, amounts)
    await session.commit()
    return [row for row in await list_pantry(session, user) if row.ingredient_id in amounts]
