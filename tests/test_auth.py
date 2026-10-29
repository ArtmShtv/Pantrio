"""End-to-end auth flow. Uses the database from .env (like test_health_db).

Each test registers a user with a random email, so runs don't collide.
"""

import secrets

from httpx import AsyncClient

from app.core.cookies import REFRESH_COOKIE


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    tag = secrets.token_hex(4)
    email, password = f"user-{tag}@example.com", "s3cret-pass"
    r = await client.post(
        "/auth/register", json={"email": email, "username": f"user-{tag}", "password": password}
    )
    assert r.status_code == 201, r.text
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    assert "refresh_token" not in r.json()  # only in the cookie
    return r.json()["access_token"], client.cookies[REFRESH_COOKIE]


async def test_login_sets_httponly_cookie_and_access_token_works(client: AsyncClient) -> None:
    access, _ = await _register_and_login(client)
    r = await client.get("/users/me", headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200


async def test_wrong_password_is_401(client: AsyncClient) -> None:
    r = await client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert r.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    assert (await client.get("/users/me")).status_code == 401
    r = await client.get("/users/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


async def test_refresh_rotates_token(client: AsyncClient) -> None:
    _, first = await _register_and_login(client)
    r = await client.post("/auth/refresh")
    assert r.status_code == 200, r.text
    second = client.cookies[REFRESH_COOKIE]
    assert second != first
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = await client.get("/users/me", headers=headers)
    assert me.status_code == 200


async def test_reusing_old_refresh_token_kills_the_session(client: AsyncClient) -> None:
    _, stolen = await _register_and_login(client)
    assert (await client.post("/auth/refresh")).status_code == 200
    current = client.cookies[REFRESH_COOKIE]

    # The attacker replays the old token: rejected...
    client.cookies.set(REFRESH_COOKIE, stolen, path="/auth")
    assert (await client.post("/auth/refresh")).status_code == 401

    # ...and the legitimate user's newer token is now revoked too.
    client.cookies.set(REFRESH_COOKIE, current, path="/auth")
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_logout_revokes_session(client: AsyncClient) -> None:
    _, token = await _register_and_login(client)
    r = await client.post("/auth/logout")
    assert r.status_code == 204
    assert REFRESH_COOKIE not in client.cookies

    client.cookies.set(REFRESH_COOKIE, token, path="/auth")
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_swagger_form_login(client: AsyncClient) -> None:
    tag = secrets.token_hex(4)
    email, password = f"form-{tag}@example.com", "s3cret-pass"
    body = {"email": email, "username": f"form-{tag}", "password": password}
    assert (await client.post("/auth/register", json=body)).status_code == 201
    # OAuth2 form: the field is called "username", but we send the email.
    r = await client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
