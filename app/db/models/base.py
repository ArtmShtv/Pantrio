import re
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, declared_attr, mapped_column

# Deterministic constraint names, so Alembic can later alter/drop them.
# Without this, Postgres invents names and autogenerate can't target them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

int_pk = Annotated[int, mapped_column(primary_key=True)]
created_at = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now()),
]
updated_at = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    ),
]

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Re-read server-generated values (created_at, updated_at) via RETURNING
    # right after INSERT/UPDATE. In async code a later lazy refresh of an
    # expired attribute raises MissingGreenlet, so fetch them eagerly.
    __mapper_args__ = {"eager_defaults": True}

    @declared_attr.directive
    def __tablename__(cls) -> str:
        # ShopProduct -> shop_products, RecipeItem -> recipe_items
        return _CAMEL_BOUNDARY.sub("_", cls.__name__).lower() + "s"
