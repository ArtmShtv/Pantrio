"""SQLAlchemy models.

Import every model module here. Alembic's autogenerate only sees tables that
are registered on `Base.metadata`, and a model is registered only when its
module has been imported. A model missing from this file is invisible to
migrations, and autogenerate would even suggest dropping its table.
"""

from app.db import Base

# from app.models.user import SocialAccount, User  # noqa: E402  (add as you create them)

__all__ = ["Base"]
