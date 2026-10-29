"""SQLAlchemy models.

Import every model module here. Alembic's autogenerate only sees tables that
are registered on `Base.metadata`, and a model is registered only when its
module has been imported. A model missing from this file is invisible to
migrations, and autogenerate would even suggest dropping its table.

In migrations/env.py:
    from app.db.models import Base
    target_metadata = Base.metadata
"""

from app.db.models.base import Base
from app.db.models.catalog import Ingredient, ShopProduct
from app.db.models.enums import AuthProvider, MealType, Unit
from app.db.models.meal import Meal, RecipeItem
from app.db.models.pantry import Leftover
from app.db.models.plan import PlanSlot, WeekPlan
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import SocialAccount, User

__all__ = [
    "AuthProvider",
    "Base",
    "Ingredient",
    "Leftover",
    "Meal",
    "MealType",
    "PlanSlot",
    "RecipeItem",
    "RefreshToken",
    "ShopProduct",
    "SocialAccount",
    "Unit",
    "User",
    "WeekPlan",
]
