import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_refresh_token, hash_refresh_token, refresh_ttl
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User


class InvalidRefreshToken(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _new_token(user_id: int, family_id: uuid.UUID) -> tuple[RefreshToken, str]:
    raw, token_hash = generate_refresh_token()
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=token_hash,
        expires_at=_now() + refresh_ttl(),
    )
    return row, raw


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def start_session(db: AsyncSession, user_id: int) -> str:
    """Call after a successful login/registration. Returns the raw refresh token."""
    row, raw = _new_token(user_id, uuid.uuid4())
    db.add(row)
    await db.commit()
    return raw


async def rotate_refresh_token(db: AsyncSession, raw: str) -> tuple[User, str]:
    """Consume `raw` and return (user, new raw refresh token).

    Raises InvalidRefreshToken if the token is unknown, expired, revoked,
    reused, or belongs to a disabled user.
    """
    token = await db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw))
        .with_for_update()  # two parallel refreshes can't both succeed
    )
    if token is None:
        raise InvalidRefreshToken

    if token.used_at is not None or token.revoked_at is not None:
        # Reuse: someone holds a copy of an old token. We can't tell who is
        # the real user, so the whole session (family) dies.
        await _revoke_family(db, token.family_id)
        await db.commit()
        raise InvalidRefreshToken

    if token.expires_at <= _now():
        raise InvalidRefreshToken

    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        await _revoke_family(db, token.family_id)
        await db.commit()
        raise InvalidRefreshToken

    token.used_at = _now()
    new_row, new_raw = _new_token(user.id, token.family_id)
    db.add(new_row)
    await db.commit()
    return user, new_raw


async def revoke_session(db: AsyncSession, raw: str) -> None:
    """Logout: revoke the session the token belongs to. Silent if unknown."""
    family_id = await db.scalar(
        select(RefreshToken.family_id).where(RefreshToken.token_hash == hash_refresh_token(raw))
    )
    if family_id is not None:
        await _revoke_family(db, family_id)
        await db.commit()
