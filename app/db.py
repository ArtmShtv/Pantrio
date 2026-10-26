"""Database engine, session factory, declarative Base and the session dependency."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

# Deterministic constraint names. Without this, Postgres invents names like
# "user_email_key", and Alembic can't reliably drop/alter a constraint later
# because it doesn't know what it is called.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


settings = get_settings()

# One engine per process: it owns the connection pool.
# Creating it does not connect yet; connections open on first use.
engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,  # drop dead connections (e.g. after a DB restart) instead of erroring
)

# expire_on_commit=False: after commit, ORM objects keep their loaded values.
# With the default (True), touching `user.email` after commit would trigger a
# lazy reload, and in async code an implicit lazy load raises MissingGreenlet.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request.

    No auto-commit here: the service/route that changes data calls
    `await session.commit()` explicitly, so it is obvious where a transaction
    ends. If the request fails before that, closing the session rolls back
    whatever wasn't committed.
    """
    async with SessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
