import asyncio

from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password, verify_password
from app.core.exceptions import UserAlreadyExistsError
from app.db.models.user import User
from app.schemas.auth import UserCreate
from app.services.user import normalize_email

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_DUMMY_HASH = hash_password("dummy-password")

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def _check_password(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, plain, hashed)


async def register_user(session: AsyncSession, user_data: UserCreate) -> User:
    email = normalize_email(user_data.email)

    existing_id = await session.scalar(
        select(User.id)
        .where(or_(User.email == email, User.username == user_data.username))
        .limit(1)
    )
    if existing_id is not None:
        raise UserAlreadyExistsError("Email or username already exists")

    user = User(
        email=email,
        username=user_data.username,
        password_hash=await asyncio.to_thread(hash_password, user_data.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise UserAlreadyExistsError("Email or username already exists") from None

    return user
