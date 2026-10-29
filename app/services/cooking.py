"""Cooking a plan slot: mark it cooked and take its ingredients out of the pantry."""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.exceptions import ConflictError
from app.db.models.plan import PlanSlot
from app.db.models.user import User
from app.services import pantry, plans
from app.services.shopping import needs_from_slots


async def _flip_cooked(session: AsyncSession, slot: PlanSlot, *, cooked: bool) -> None:
    # Conditional UPDATE instead of "if slot.cooked_at: ...; slot.cooked_at = now":
    # two parallel requests both pass a Python check, but only one of them can
    # match `cooked_at IS NULL` in the database. The other gets 0 rows -> 409.
    now = datetime.now(UTC) if cooked else None
    condition = PlanSlot.cooked_at.is_(None) if cooked else PlanSlot.cooked_at.is_not(None)
    result = await session.execute(
        update(PlanSlot)
        .where(PlanSlot.id == slot.id, condition)
        .values(cooked_at=now)
        .returning(PlanSlot.id)
    )
    if result.scalar_one_or_none() is None:
        await session.rollback()
        raise ConflictError("This slot is already cooked" if cooked else "This slot isn't cooked")
    # The DB already has the new value; tell the ORM without queuing another UPDATE.
    set_committed_value(slot, "cooked_at", now)


async def cook(
    session: AsyncSession, user: User, plan_id: int, slot_id: int
) -> tuple[PlanSlot, list[pantry.Change]]:
    slot = await plans.get_slot(session, user, plan_id, slot_id)
    grams = needs_from_slots([slot])  # computed before the flip: it skips cooked slots
    await _flip_cooked(session, slot, cooked=True)
    changes = await pantry.subtract_grams(session, user.id, grams)
    await session.commit()
    return slot, changes


async def uncook(
    session: AsyncSession, user: User, plan_id: int, slot_id: int
) -> tuple[PlanSlot, list[pantry.Change]]:
    """Adds back the full recipe amounts, even where cooking stopped at 0."""
    slot = await plans.get_slot(session, user, plan_id, slot_id)
    await _flip_cooked(session, slot, cooked=False)
    grams = needs_from_slots([slot])
    before = {
        row.ingredient_id: row.quantity_g
        for row in await pantry.list_pantry(session, user)
        if row.ingredient_id in grams
    }
    await pantry.add_grams(session, user.id, grams)
    await session.commit()
    changes = [
        pantry.Change(i, before.get(i, 0), before.get(i, 0) + g) for i, g in sorted(grams.items())
    ]
    return slot, changes
