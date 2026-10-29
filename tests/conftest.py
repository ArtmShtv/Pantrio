import secrets
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import engine, get_session
from app.db.models.user import User
from app.main import create_app

Headers = dict[str, str]


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back after the test.

    join_transaction_mode="create_savepoint": the app's own commit() calls
    only release a savepoint, so nothing a test writes reaches the database.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def make_user(client: AsyncClient, db_session: AsyncSession) -> Callable[..., Awaitable[Headers]]:
    """Register + log in a fresh user; returns its Authorization header."""

    async def _make(*, admin: bool = False) -> Headers:
        tag = secrets.token_hex(4)
        email, password = f"u-{tag}@example.com", "s3cret-pass"
        r = await client.post(
            "/auth/register", json={"email": email, "username": f"u-{tag}", "password": password}
        )
        assert r.status_code == 201, r.text
        if admin:
            await db_session.execute(
                update(User).where(User.id == r.json()["id"]).values(is_admin=True)
            )
            db_session.expire_all()
        r = await client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _make
