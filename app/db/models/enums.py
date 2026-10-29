"""Enums shared by models and (later) Pydantic schemas.

Stored as VARCHAR + CHECK constraint, not as native Postgres ENUM types.
Adding a value to a native ENUM needs `ALTER TYPE ... ADD VALUE`, which
Alembic autogenerate does not detect and which can't run inside a transaction
on older Postgres versions. A CHECK constraint is just dropped and recreated.
"""

from enum import StrEnum

from sqlalchemy import Enum


class Unit(StrEnum):
    G = "g"
    ML = "ml"
    PIECE = "piece"


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class AuthProvider(StrEnum):
    GOOGLE = "google"
    YANDEX = "yandex"
    VK = "vk"


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Column type for a StrEnum.

    - values_callable: store "piece", not the member name "PIECE".
    - create_constraint: in SQLAlchemy 2.0 the CHECK is off by default for
      non-native enums; without it the DB would accept any string.
    - name: becomes the CHECK name through the naming convention
      (ck_recipe_items_unit).
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(m.value) for m in enum_cls),
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
