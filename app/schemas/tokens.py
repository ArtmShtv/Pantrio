from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Body of every login/refresh response.

    The refresh token is deliberately absent: it travels only in the
    httpOnly cookie. Field names follow OAuth 2.0 (RFC 6749 §5.1), which is
    also what the Swagger "Authorize" button expects from /auth/token.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires
