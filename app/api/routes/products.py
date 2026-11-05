from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentUser
from app.schemas.common import Page
from app.schemas.ingredients import CreateScope, Scope
from app.schemas.products import ProductCreate, ProductRead, ProductUpdate, ProductWithIngredient
from app.services import products as service

router = APIRouter(prefix="/products", tags=["products"])

_403 = {status.HTTP_403_FORBIDDEN: {"description": "Global product, admins only"}}
_404 = {status.HTTP_404_NOT_FOUND: {"description": "Not found or not visible to you"}}
_422 = {422: {"description": "Invalid body, or the ingredient can't be measured in pack_unit"}}


@router.get(
    "",
    response_model=Page[ProductWithIngredient],
    summary="Visible products, by ingredient name, cheapest per gram first",
)
async def list_products(
    user: CurrentUser,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    ingredient_id: int | None = None,
    shop_name: Annotated[str | None, Query(max_length=100)] = None,
    scope: Scope = Scope.ALL,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await service.list_products(
        db,
        user,
        q=q,
        ingredient_id=ingredient_id,
        shop_name=shop_name,
        scope=scope,
        limit=limit,
        offset=offset,
    )
    return Page(items=[ProductWithIngredient.from_model(p) for p in rows], total=total)


@router.get("/{product_id}", response_model=ProductWithIngredient, responses=_404)
async def get_product(product_id: int, user: CurrentUser, db: DB):
    product = await service.get_visible(db, user, product_id, with_ingredient=True)
    return ProductWithIngredient.from_model(product)


@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    responses={**_403, **_404, **_422},
)
async def create_product(
    data: ProductCreate, user: CurrentUser, db: DB, scope: CreateScope = CreateScope.PRIVATE
):
    product = await service.create_product(db, user, data, make_global=scope == CreateScope.GLOBAL)
    return ProductRead.from_model(product)


@router.patch("/{product_id}", response_model=ProductRead, responses={**_403, **_404, **_422})
async def update_product(product_id: int, data: ProductUpdate, user: CurrentUser, db: DB):
    product = await service.update_product(
        db, user, product_id, data.model_dump(exclude_unset=True)
    )
    return ProductRead.from_model(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, responses={**_403, **_404})
async def delete_product(product_id: int, user: CurrentUser, db: DB) -> None:
    await service.delete_product(db, user, product_id)
