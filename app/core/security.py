"""Token primitives: stateless JWT access tokens and opaque refresh tokens.

Access token: a short-lived JWT. Verified by signature alone, never stored,
so it can't be revoked; the short TTL limits the damage if one leaks.

Refresh token: a random string, not a JWT. The server has to look it up in
the database anyway (to rotate or revoke it), so a signature would add
nothing. Only its SHA-256 hash is stored: a leaked DB dump can't be replayed.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings


def access_ttl() -> timedelta:
    return timedelta(minutes=get_settings().ACCESS_TOKEN_TTL_MINUTES)


def refresh_ttl() -> timedelta:
    return timedelta(days=get_settings().REFRESH_TOKEN_TTL_DAYS)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + access_ttl(),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "type": "access",
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET.get_secret_value(), algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    """Raise jwt.InvalidTokenError (or a subclass) if the token is not valid."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.JWT_SECRET.get_secret_value(),
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def generate_refresh_token() -> tuple[str, str]:
    """Return (raw token for the client, hash for the database)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
