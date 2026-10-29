from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser
from app.schemas.ingredients import CreateScope
from app.schemas.products import ProductCreate, ProductRead, ProductUpdate
from app.services import products as service

router = APIRouter(prefix="/products", tags=["products"])

_403 = {status.HTTP_403_FORBIDDEN: {"description": "Global product, admins only"}}
_404 = {status.HTTP_404_NOT_FOUND: {"description": "Not found or not visible to you"}}
_422 = {422: {"description": "Invalid body, or the ingredient can't be measured in pack_unit"}}


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
