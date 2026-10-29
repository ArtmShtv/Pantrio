from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_token
from app.db.models.user import RefreshToken
from app.schemas.tokens import TokenPairSchema


async def issue_token_pair(session: AsyncSession, user_id: int) -> TokenPairSchema:
    """Create an access + refresh pair and record the refresh token.

    The access token is stateless: it is short-lived and never stored.
    The refresh token is long-lived, so it gets a row keyed by its jti.
    That row is what lets /refresh rotate it and /logout revoke it.
    """
    access = create_token(user_id, "access")
    refresh = create_token(user_id, "refresh")

    session.add(
        RefreshToken(user_id=user_id, jti=refresh.jti, expires_at=refresh.expires_at)
    )
    await session.commit()

    return TokenPairSchema(access_token=access.token, refresh_token=refresh.token)
