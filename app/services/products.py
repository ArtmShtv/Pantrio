from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.db.models.catalog import Ingredient, ShopProduct
from app.db.models.enums import Unit
from app.db.models.user import User
from app.schemas.products import ProductCreate
from app.services import ingredients
from app.services.calc import GRAMS, UnitNotSupportedError, to_grams


def visible_to(user: User) -> ColumnElement[bool]:
    return or_(ShopProduct.created_by_id.is_(None), ShopProduct.created_by_id == user.id)


async def list_for_ingredient(
    session: AsyncSession, user: User, ingredient_id: int
) -> Sequence[ShopProduct]:
    """Cheapest per gram first. Raises NotFoundError if the ingredient isn't visible."""
    await ingredients.get_visible(session, user, ingredient_id)
    rows = await session.scalars(
        select(ShopProduct)
        .where(ShopProduct.ingredient_id == ingredient_id, visible_to(user))
        .order_by(ShopProduct.price / ShopProduct.pack_size_g, ShopProduct.id)
    )
    return rows.all()


async def get_visible(session: AsyncSession, user: User, product_id: int) -> ShopProduct:
    product = await session.scalar(
        select(ShopProduct).where(ShopProduct.id == product_id, visible_to(user))
    )
    if product is None:
        raise NotFoundError("Product not found")
    return product


def _ensure_can_edit(user: User, product: ShopProduct) -> None:
    if product.created_by_id is None and not user.is_admin:
        raise PermissionDeniedError("Only admins can change global products")


def _pack_grams(ing: Ingredient, size: Decimal, unit: Unit) -> Decimal:
    try:
        grams = to_grams(
            size, unit, grams_per_piece=ing.grams_per_piece, grams_per_ml=ing.grams_per_ml
        )
    except UnitNotSupportedError as e:
        raise DomainValidationError(f"{ing.name!r}: {e}") from None
    grams = grams.quantize(GRAMS)
    if grams <= 0:
        # e.g. 0.001 ml rounds to 0.00 g; the DB CHECK would reject it anyway.
        raise DomainValidationError("pack is too small")
    return grams


async def create_product(
    session: AsyncSession, user: User, data: ProductCreate, *, make_global: bool
) -> ShopProduct:
    if make_global and not user.is_admin:
        raise PermissionDeniedError("Only admins can create global products")
    ing = await ingredients.get_visible(session, user, data.ingredient_id)
    if make_global and ing.created_by_id is not None:
        # Other users can't see a private ingredient, so a global product for it
        # would be invisible to them anyway, and break when the owner deletes it.
        raise DomainValidationError("A global product needs a global ingredient")

    product = ShopProduct(
        ingredient_id=ing.id,
        created_by_id=None if make_global else user.id,
        name=data.name,
        shop_name=data.shop_name,
        pack_size_g=_pack_grams(ing, data.pack_size, data.pack_unit),
        price=data.price,
    )
    session.add(product)
    await session.commit()
    return product


async def update_product(
    session: AsyncSession, user: User, product_id: int, changes: dict[str, Any]
) -> ShopProduct:
    product = await get_visible(session, user, product_id)
    _ensure_can_edit(user, product)

    if "pack_size" in changes:
        ing = await session.get_one(Ingredient, product.ingredient_id)
        product.pack_size_g = _pack_grams(ing, changes.pop("pack_size"), changes.pop("pack_unit"))
    for field, value in changes.items():
        setattr(product, field, value)
    await session.commit()
    return product


async def delete_product(session: AsyncSession, user: User, product_id: int) -> None:
    product = await get_visible(session, user, product_id)
    _ensure_can_edit(user, product)
    await session.delete(product)
    await session.commit()
