from sqlalchemy.exc import IntegrityError


def constraint_name(exc: IntegrityError) -> str | None:
    """Name of the violated constraint, e.g. "uq_meals_created_by_id_name".

    The names are predictable thanks to the naming convention in models/base.py.
    asyncpg puts the original error (with .constraint_name) in __cause__.
    """
    return getattr(exc.orig.__cause__, "constraint_name", None)
