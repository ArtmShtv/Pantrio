from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import access_ttl, create_access_token
from app.schemas.tokens import TokenResponse
from app.services.sessions import start_session


def token_response(user_id: int) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id),
        expires_in=int(access_ttl().total_seconds()),
    )


async def issue_tokens(session: AsyncSession, user_id: int) -> tuple[TokenResponse, str]:
    """Start a new login session.

    Returns (response body with the access token, raw refresh token).
    The caller puts the raw refresh token into the cookie.
    """
    raw_refresh = await start_session(session, user_id)
    return token_response(user_id), raw_refresh
