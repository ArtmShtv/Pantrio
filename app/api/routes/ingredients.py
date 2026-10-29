from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentUser
from app.schemas.common import Page
from app.schemas.ingredients import (
    CreateScope,
    IngredientCreate,
    IngredientDetail,
    IngredientRead,
    IngredientUpdate,
    Scope,
)
from app.schemas.products import ProductRead
from app.services import ingredients as service
from app.services import products as products_service

router = APIRouter(prefix="/ingredients", tags=["ingredients"])

_404 = {status.HTTP_404_NOT_FOUND: {"description": "Not found or not visible to you"}}
_403 = {status.HTTP_403_FORBIDDEN: {"description": "Global ingredient, admins only"}}


@router.get("", response_model=Page[IngredientRead])
async def list_ingredients(
    user: CurrentUser,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    scope: Scope = Scope.ALL,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await service.list_ingredients(
        db, user, q=q, scope=scope, limit=limit, offset=offset
    )
    return Page(items=[IngredientRead.from_model(i) for i in rows], total=total)


@router.get("/{ingredient_id}", response_model=IngredientDetail, responses=_404)
async def get_ingredient(ingredient_id: int, user: CurrentUser, db: DB):
    ing = await service.get_visible(db, user, ingredient_id)
    products = await products_service.list_for_ingredient(db, user, ingredient_id)
    return IngredientDetail(
        **IngredientRead.from_model(ing).model_dump(),
        products=[ProductRead.from_model(p) for p in products],
    )


@router.get(
    "/{ingredient_id}/products",
    response_model=list[ProductRead],
    summary="Products for this ingredient, cheapest per gram first",
    responses=_404,
)
async def list_products(ingredient_id: int, user: CurrentUser, db: DB):
    products = await products_service.list_for_ingredient(db, user, ingredient_id)
    return [ProductRead.from_model(p) for p in products]


@router.post(
    "",
    response_model=IngredientRead,
    status_code=status.HTTP_201_CREATED,
    responses={**_403, status.HTTP_409_CONFLICT: {"description": "Name already exists"}},
)
async def create_ingredient(
    data: IngredientCreate, user: CurrentUser, db: DB, scope: CreateScope = CreateScope.PRIVATE
):
    ing = await service.create_ingredient(db, user, data, make_global=scope == CreateScope.GLOBAL)
    return IngredientRead.from_model(ing)


@router.patch(
    "/{ingredient_id}",
    response_model=IngredientRead,
    responses={
        **_403,
        **_404,
        status.HTTP_409_CONFLICT: {"description": "Name taken, or a removed unit is in use"},
    },
)
async def update_ingredient(ingredient_id: int, data: IngredientUpdate, user: CurrentUser, db: DB):
    ing = await service.update_ingredient(
        db, user, ingredient_id, data.model_dump(exclude_unset=True)
    )
    return IngredientRead.from_model(ing)


@router.delete(
    "/{ingredient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_403, **_404, status.HTTP_409_CONFLICT: {"description": "Used in a meal"}},
)
async def delete_ingredient(ingredient_id: int, user: CurrentUser, db: DB) -> None:
    await service.delete_ingredient(db, user, ingredient_id)
