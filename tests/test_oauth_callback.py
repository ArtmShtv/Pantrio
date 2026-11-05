from urllib.parse import parse_qs, urlsplit

import pytest
from authlib.integrations.starlette_client import OAuthError
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import auth as auth_routes
from app.core.config import get_settings
from app.core.cookies import REFRESH_COOKIE, REFRESH_COOKIE_PATH
from app.db.models.user import User


class FakeOAuthClient:
    def __init__(self, token: dict | None = None, error: Exception | None = None) -> None:
        self.token = token
        self.error = error

    async def authorize_access_token(self, request) -> dict:
        if self.error is not None:
            raise self.error
        return self.token


def use_fake_client(monkeypatch: pytest.MonkeyPatch, client: FakeOAuthClient) -> None:
    monkeypatch.setattr(auth_routes, "get_oauth_client", lambda provider: client)


def expected_target() -> str:
    return f"{get_settings().FRONTEND_URL}/auth/callback"


def error_of(location: str) -> str | None:
    parts = urlsplit(location)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == expected_target()
    return parse_qs(parts.query).get("error", [None])[0]


async def test_success_sets_cookie_and_redirects(client: AsyncClient, monkeypatch) -> None:
    claims = {"sub": "google-123", "email": "oauth-new@example.com", "email_verified": True}
    use_fake_client(monkeypatch, FakeOAuthClient(token={"userinfo": claims}))

    r = await client.get("/auth/google/callback")

    assert r.status_code == 302
    assert error_of(r.headers["location"]) is None
    assert "access_token" not in r.text
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{REFRESH_COOKIE}=") and f"Path={REFRESH_COOKIE_PATH}" in cookie

    refreshed = await client.post("/auth/refresh")
    assert refreshed.status_code == 200
    me = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    )
    assert me.json()["email"] == "oauth-new@example.com"


async def test_provider_error_redirects_with_code(client: AsyncClient, monkeypatch) -> None:
    use_fake_client(monkeypatch, FakeOAuthClient(error=OAuthError(error="access_denied")))
    r = await client.get("/auth/google/callback")
    assert r.status_code == 302
    assert error_of(r.headers["location"]) == "provider_error"
    assert REFRESH_COOKIE not in client.cookies


async def test_missing_identity_redirects_with_code(client: AsyncClient, monkeypatch) -> None:
    use_fake_client(monkeypatch, FakeOAuthClient(token={}))
    r = await client.get("/auth/google/callback")
    assert error_of(r.headers["location"]) == "provider_error"


async def test_unverified_email_redirects_with_code(client: AsyncClient, monkeypatch) -> None:
    claims = {"sub": "google-456", "email": "oauth-unverified@example.com"}
    use_fake_client(monkeypatch, FakeOAuthClient(token={"userinfo": claims}))
    r = await client.get("/auth/google/callback")
    assert error_of(r.headers["location"]) == "email_not_verified"


async def test_password_account_conflict_redirects_with_code(
    client: AsyncClient, monkeypatch
) -> None:
    body = {
        "email": "oauth-taken@example.com",
        "username": "oauth-taken",
        "password": "s3cret-pass",
    }
    assert (await client.post("/auth/register", json=body)).status_code == 201
    client.cookies.clear()
    claims = {"sub": "google-789", "email": "oauth-taken@example.com", "email_verified": True}
    use_fake_client(monkeypatch, FakeOAuthClient(token={"userinfo": claims}))

    r = await client.get("/auth/google/callback")
    assert error_of(r.headers["location"]) == "account_exists"


async def test_disabled_account_redirects_with_code(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    claims = {"sub": "google-999", "email": "oauth-disabled@example.com", "email_verified": True}
    use_fake_client(monkeypatch, FakeOAuthClient(token={"userinfo": claims}))
    assert (await client.get("/auth/google/callback")).status_code == 302
    client.cookies.clear()

    await db_session.execute(
        update(User).where(User.email == "oauth-disabled@example.com").values(is_active=False)
    )
    db_session.expire_all()

    r = await client.get("/auth/google/callback")
    assert error_of(r.headers["location"]) == "account_disabled"


async def test_unconfigured_provider_redirects_with_code(client: AsyncClient) -> None:
    r = await client.get("/auth/vk/callback")
    assert r.status_code == 302
    assert error_of(r.headers["location"]) == "not_configured"
