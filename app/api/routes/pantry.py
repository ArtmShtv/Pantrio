from fastapi import APIRouter, Response, status

from app.api.deps import DB, CurrentUser
from app.db.models.pantry import Leftover
from app.schemas.pantry import PantryItemRead, PantrySet, Purchase
from app.schemas.products import IngredientRef
from app.services import pantry as service

router = APIRouter(prefix="/pantry", tags=["pantry"])


def to_read(row: Leftover) -> PantryItemRead:
    return PantryItemRead(
        ingredient=IngredientRef(id=row.ingredient.id, name=row.ingredient.name),
        quantity_g=row.quantity_g,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[PantryItemRead])
async def list_pantry(user: CurrentUser, db: DB):
    return [to_read(r) for r in await service.list_pantry(db, user)]


@router.put(
    "/{ingredient_id}",
    response_model=PantryItemRead,
    summary="Set how much you have (not add). Quantity 0 removes it.",
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Quantity was 0; the item was removed"},
        status.HTTP_404_NOT_FOUND: {"description": "Ingredient not found"},
        422: {"description": "Invalid body, or the ingredient can't be measured in unit"},
    },
)
async def set_quantity(ingredient_id: int, data: PantrySet, user: CurrentUser, db: DB):
    row = await service.set_quantity(db, user, ingredient_id, data.quantity, data.unit)
    if row is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return to_read(row)


@router.delete("/{ingredient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(ingredient_id: int, user: CurrentUser, db: DB) -> None:
    await service.delete_item(db, user, ingredient_id)


@router.post(
    "/purchases",
    response_model=list[PantryItemRead],
    summary="I bought these: add the amounts to the pantry",
    responses={422: {"description": "Invalid body, unknown ingredient, or unit not supported"}},
)
async def record_purchase(data: Purchase, user: CurrentUser, db: DB):
    return [to_read(r) for r in await service.record_purchase(db, user, data.items)]
