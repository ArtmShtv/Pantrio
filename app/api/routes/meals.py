from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentUser
from app.schemas.common import Page
from app.schemas.ingredients import CreateScope, Scope
from app.schemas.meals import MealDetail, MealListItem, MealWrite
from app.services import meals as service

router = APIRouter(prefix="/meals", tags=["meals"])

_403 = {status.HTTP_403_FORBIDDEN: {"description": "Global meal, admins only"}}
_404 = {status.HTTP_404_NOT_FOUND: {"description": "Not found or not visible to you"}}
_409_NAME = {status.HTTP_409_CONFLICT: {"description": "Name already exists"}}
_422 = {422: {"description": "Invalid body, unknown ingredient, or unit not supported"}}


@router.get("", response_model=Page[MealListItem])
async def list_meals(
    user: CurrentUser,
    db: DB,
    q: Annotated[str | None, Query(max_length=150)] = None,
    scope: Scope = Scope.ALL,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await service.list_meals(db, user, q=q, scope=scope, limit=limit, offset=offset)
    return Page(items=[service.to_list_item(m) for m in rows], total=total)


@router.get("/{meal_id}", response_model=MealDetail, responses=_404)
async def get_meal(meal_id: int, user: CurrentUser, db: DB):
    return service.to_detail(await service.get_visible(db, user, meal_id))


@router.post(
    "",
    response_model=MealDetail,
    status_code=status.HTTP_201_CREATED,
    responses={**_403, **_409_NAME, **_422},
)
async def create_meal(
    data: MealWrite, user: CurrentUser, db: DB, scope: CreateScope = CreateScope.PRIVATE
):
    meal = await service.create_meal(db, user, data, make_global=scope == CreateScope.GLOBAL)
    return service.to_detail(meal)


@router.put(
    "/{meal_id}",
    response_model=MealDetail,
    summary="Replace the meal, including the whole item list",
    responses={**_403, **_404, **_409_NAME, **_422},
)
async def replace_meal(meal_id: int, data: MealWrite, user: CurrentUser, db: DB):
    return service.to_detail(await service.replace_meal(db, user, meal_id, data))


@router.delete(
    "/{meal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_403, **_404, status.HTTP_409_CONFLICT: {"description": "Used in a plan"}},
)
async def delete_meal(meal_id: int, user: CurrentUser, db: DB) -> None:
    await service.delete_meal(db, user, meal_id)
