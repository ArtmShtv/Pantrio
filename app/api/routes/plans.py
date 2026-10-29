from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentUser
from app.schemas.common import Page
from app.schemas.pantry import CookResult, PantryChange
from app.schemas.plans import PlanCreate, PlanDetail, PlanListItem, SlotCreate, SlotRead, SlotUpdate
from app.schemas.products import IngredientRef
from app.schemas.shopping import ShoppingListRead
from app.services import cooking, shopping
from app.services import plans as service

router = APIRouter(prefix="/plans", tags=["plans"])

_404 = {status.HTTP_404_NOT_FOUND: {"description": "Plan or slot not found"}}
_422_MEAL = {422: {"description": "Invalid body or unknown meal"}}


@router.get("", response_model=Page[PlanListItem], summary="Your plans, newest first")
async def list_plans(
    user: CurrentUser,
    db: DB,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await service.list_plans(
        db, user, date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )
    items = [PlanListItem(id=p.id, start_date=p.start_date, slot_count=n) for p, n in rows]
    return Page(items=items, total=total)


@router.post(
    "",
    response_model=PlanDetail,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "A plan for this week exists"}},
)
async def create_plan(data: PlanCreate, user: CurrentUser, db: DB):
    return service.to_detail(await service.create_plan(db, user, data.start_date))


@router.get("/{plan_id}", response_model=PlanDetail, responses=_404)
async def get_plan(plan_id: int, user: CurrentUser, db: DB):
    return service.to_detail(await service.get_plan(db, user, plan_id))


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_404)
async def delete_plan(plan_id: int, user: CurrentUser, db: DB) -> None:
    await service.delete_plan(db, user, plan_id)


@router.post(
    "/{plan_id}/slots",
    response_model=SlotRead,
    status_code=status.HTTP_201_CREATED,
    responses={**_404, **_422_MEAL},
)
async def add_slot(plan_id: int, data: SlotCreate, user: CurrentUser, db: DB):
    return service.to_slot_read(await service.add_slot(db, user, plan_id, data))


@router.patch(
    "/{plan_id}/slots/{slot_id}",
    response_model=SlotRead,
    responses={
        **_404,
        **_422_MEAL,
        status.HTTP_409_CONFLICT: {"description": "Slot is cooked; un-cook it first"},
    },
)
async def update_slot(plan_id: int, slot_id: int, data: SlotUpdate, user: CurrentUser, db: DB):
    slot = await service.update_slot(
        db, user, plan_id, slot_id, data.model_dump(exclude_unset=True)
    )
    return service.to_slot_read(slot)


@router.delete("/{plan_id}/slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_404)
async def delete_slot(plan_id: int, slot_id: int, user: CurrentUser, db: DB) -> None:
    await service.delete_slot(db, user, plan_id, slot_id)


@router.get(
    "/{plan_id}/shopping-list",
    response_model=ShoppingListRead,
    summary="What to buy for this plan's uncooked meals",
    responses=_404,
)
async def shopping_list(plan_id: int, user: CurrentUser, db: DB, use_pantry: bool = True):
    result = await shopping.build_shopping_list(db, user, plan_id, use_pantry=use_pantry)
    return ShoppingListRead.from_service(result)


def _cook_result(slot, changes, names: dict[int, str]) -> CookResult:
    return CookResult(
        slot=service.to_slot_read(slot),
        pantry_changes=[
            PantryChange(
                ingredient=IngredientRef(id=c.ingredient_id, name=names[c.ingredient_id]),
                before_g=c.before_g,
                after_g=c.after_g,
            )
            for c in changes
        ],
    )


def _names(slot) -> dict[int, str]:
    return {i.ingredient.id: i.ingredient.name for i in slot.meal.items}


@router.post(
    "/{plan_id}/slots/{slot_id}/cook",
    response_model=CookResult,
    summary="Mark as cooked and take the ingredients out of the pantry",
    responses={**_404, status.HTTP_409_CONFLICT: {"description": "Already cooked"}},
)
async def cook_slot(plan_id: int, slot_id: int, user: CurrentUser, db: DB):
    slot, changes = await cooking.cook(db, user, plan_id, slot_id)
    return _cook_result(slot, changes, _names(slot))


@router.delete(
    "/{plan_id}/slots/{slot_id}/cook",
    response_model=CookResult,
    summary="Undo cooking: put the ingredients back into the pantry",
    responses={**_404, status.HTTP_409_CONFLICT: {"description": "Not cooked"}},
)
async def uncook_slot(plan_id: int, slot_id: int, user: CurrentUser, db: DB):
    slot, changes = await cooking.uncook(db, user, plan_id, slot_id)
    return _cook_result(slot, changes, _names(slot))
