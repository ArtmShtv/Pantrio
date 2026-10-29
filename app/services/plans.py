from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.db.errors import constraint_name
from app.db.models.enums import MealType
from app.db.models.meal import Meal, RecipeItem
from app.db.models.plan import PlanSlot, WeekPlan
from app.db.models.user import User
from app.schemas.meals import NutritionRead
from app.schemas.plans import DayRead, MealRef, PlanDetail, SlotCreate, SlotRead
from app.services import meals as meals_service
from app.services.calc import Nutrition, total

_MEAL_WITH_ITEMS = (
    selectinload(PlanSlot.meal).selectinload(Meal.items).selectinload(RecipeItem.ingredient)
)
_MEAL_TYPE_ORDER = {t: i for i, t in enumerate(MealType)}  # breakfast, lunch, dinner, snack


def slot_nutrition(slot: PlanSlot) -> Nutrition:
    meal = slot.meal
    return meals_service.meal_total(meal).scale(slot.servings / meal.servings)


def to_slot_read(slot: PlanSlot, n: Nutrition | None = None) -> SlotRead:
    return SlotRead(
        id=slot.id,
        day=slot.day,
        meal_type=slot.meal_type,
        meal=MealRef(id=slot.meal.id, name=slot.meal.name),
        servings=slot.servings,
        cooked_at=slot.cooked_at,
        **NutritionRead.from_calc(n or slot_nutrition(slot)).model_dump(),
    )


def to_detail(plan: WeekPlan) -> PlanDetail:
    by_day: dict[int, list[PlanSlot]] = {d: [] for d in range(7)}
    for slot in plan.slots:
        by_day[slot.day].append(slot)

    days, day_totals = [], []
    for d, slots in by_day.items():
        slots.sort(key=lambda s: (_MEAL_TYPE_ORDER[s.meal_type], s.id))
        parts = [slot_nutrition(s) for s in slots]
        day_total = total(parts)
        if slots:
            day_totals.append(day_total)
        days.append(
            DayRead(
                day=d,
                date=plan.start_date + timedelta(days=d),
                slots=[to_slot_read(s, n) for s, n in zip(slots, parts, strict=True)],
                total=NutritionRead.from_calc(day_total),
            )
        )

    week = total(day_totals)
    # Average over days that have food planned, not over 7: a plan with only
    # weekdays filled in shouldn't show a misleadingly low daily intake.
    average = week.scale(Decimal(1) / len(day_totals)) if day_totals else Nutrition()
    return PlanDetail(
        id=plan.id,
        start_date=plan.start_date,
        days=days,
        week_total=NutritionRead.from_calc(week),
        daily_average=NutritionRead.from_calc(average),
    )


async def list_plans(
    session: AsyncSession,
    user: User,
    *,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[tuple[WeekPlan, int]], int]:
    conditions = [WeekPlan.user_id == user.id]
    if date_from is not None:
        conditions.append(WeekPlan.start_date >= date_from)
    if date_to is not None:
        conditions.append(WeekPlan.start_date <= date_to)

    total_count = await session.scalar(
        select(func.count()).select_from(WeekPlan).where(*conditions)
    )
    slot_count = (
        select(func.count())
        .where(PlanSlot.plan_id == WeekPlan.id)
        .correlate(WeekPlan)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(WeekPlan, slot_count)
        .where(*conditions)
        .order_by(WeekPlan.start_date.desc())
        .limit(limit)
        .offset(offset)
    )
    return [(plan, count) for plan, count in rows], total_count or 0


async def get_plan(session: AsyncSession, user: User, plan_id: int) -> WeekPlan:
    plan = await session.scalar(
        select(WeekPlan)
        .options(selectinload(WeekPlan.slots).options(_MEAL_WITH_ITEMS))
        .where(WeekPlan.id == plan_id, WeekPlan.user_id == user.id)
    )
    if plan is None:
        raise NotFoundError("Plan not found")
    return plan


async def create_plan(session: AsyncSession, user: User, start_date: date) -> WeekPlan:
    existing = await session.scalar(
        select(WeekPlan.id).where(WeekPlan.user_id == user.id, WeekPlan.start_date == start_date)
    )
    if existing is not None:
        raise ConflictError(f"A plan for this week already exists (id {existing})")

    plan = WeekPlan(user_id=user.id, start_date=start_date)
    plan.slots = []
    session.add(plan)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        if constraint_name(e) == "uq_week_plans_user_id_start_date":
            raise ConflictError("A plan for this week already exists") from None
        raise
    return plan


async def delete_plan(session: AsyncSession, user: User, plan_id: int) -> None:
    plan = await session.scalar(
        select(WeekPlan).where(WeekPlan.id == plan_id, WeekPlan.user_id == user.id)
    )
    if plan is None:
        raise NotFoundError("Plan not found")
    await session.delete(plan)
    await session.commit()


async def _get_owned_plan_id(session: AsyncSession, user: User, plan_id: int) -> int:
    found = await session.scalar(
        select(WeekPlan.id).where(WeekPlan.id == plan_id, WeekPlan.user_id == user.id)
    )
    if found is None:
        raise NotFoundError("Plan not found")
    return found


async def get_slot(session: AsyncSession, user: User, plan_id: int, slot_id: int) -> PlanSlot:
    await _get_owned_plan_id(session, user, plan_id)
    slot = await session.scalar(
        select(PlanSlot)
        .options(_MEAL_WITH_ITEMS)
        .where(PlanSlot.id == slot_id, PlanSlot.plan_id == plan_id)
    )
    if slot is None:
        raise NotFoundError("Slot not found")
    return slot


async def _visible_meal(session: AsyncSession, user: User, meal_id: int) -> Meal:
    try:
        return await meals_service.get_visible(session, user, meal_id)
    except NotFoundError:
        # The meal is in the body, not the URL: a bad reference is a 422.
        raise DomainValidationError(f"Unknown meal id: {meal_id}") from None


async def add_slot(session: AsyncSession, user: User, plan_id: int, data: SlotCreate) -> PlanSlot:
    await _get_owned_plan_id(session, user, plan_id)
    meal = await _visible_meal(session, user, data.meal_id)
    slot = PlanSlot(
        plan_id=plan_id,
        day=data.day,
        meal_type=data.meal_type,
        meal=meal,
        servings=data.servings if data.servings is not None else Decimal(meal.servings),
    )
    session.add(slot)
    await session.commit()
    return slot


async def update_slot(
    session: AsyncSession, user: User, plan_id: int, slot_id: int, changes: dict[str, Any]
) -> PlanSlot:
    slot = await get_slot(session, user, plan_id, slot_id)
    if slot.cooked_at is not None:
        # Cooking subtracted this slot's ingredients from the pantry; editing it
        # now would make the pantry and the plan disagree.
        raise ConflictError("This slot is already cooked; un-cook it first")

    if "meal_id" in changes:
        slot.meal = await _visible_meal(session, user, changes.pop("meal_id"))
    for field, value in changes.items():
        setattr(slot, field, value)
    await session.commit()
    return slot


async def delete_slot(session: AsyncSession, user: User, plan_id: int, slot_id: int) -> None:
    slot = await get_slot(session, user, plan_id, slot_id)
    await session.delete(slot)
    await session.commit()
