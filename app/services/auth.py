import asyncio

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserAlreadyExistsError
from app.db.models.user import User
from app.schemas.auth import UserCreateSchema
from app.auth.security import hash_password, _check_password
from app.services.user import normalize_email, get_user_by_email


_DUMMY_HASH = hash_password("dummy-password")


async def register_user(session: AsyncSession, user_data: UserCreateSchema) -> User:
    email = normalize_email(user_data.email)

    result = await session.execute(
        select(User.id).where(
            (User.email == email) | (User.username == user_data.username)
        )
    )
    if result.first():
        raise UserAlreadyExistsError("Email or username already exists")

    user = User(
        email=email,
        username=user_data.username,
        password=await asyncio.to_thread(hash_password, user_data.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise UserAlreadyExistsError("Email or username already exists") from None

    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(session, email)

    has_password = user is not None and user.password_hash is not None
    hashed = user.password_hash if has_password else _DUMMY_HASH
    password_ok = await _check_password(password, hashed)

    if not has_password or not password_ok:
        return None
    if not user.is_active:
        return None
    return user