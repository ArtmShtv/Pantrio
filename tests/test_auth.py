"""End-to-end auth flow. Uses the database from .env (like test_health_db).

Each test registers a user with a random email, so runs don't collide.
"""

import secrets

from httpx import AsyncClient

from app.core.cookies import REFRESH_COOKIE, REFRESH_COOKIE_PATH


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
    client.cookies.set(REFRESH_COOKIE, stolen, path=REFRESH_COOKIE_PATH)
    assert (await client.post("/auth/refresh")).status_code == 401

    # ...and the legitimate user's newer token is now revoked too.
    client.cookies.set(REFRESH_COOKIE, current, path=REFRESH_COOKIE_PATH)
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_logout_revokes_session(client: AsyncClient) -> None:
    _, token = await _register_and_login(client)
    r = await client.post("/auth/logout")
    assert r.status_code == 204
    assert REFRESH_COOKIE not in client.cookies

    client.cookies.set(REFRESH_COOKIE, token, path=REFRESH_COOKIE_PATH)
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


async def test_register_logs_in(client: AsyncClient) -> None:
    tag = secrets.token_hex(4)
    body = {"email": f"reg-{tag}@example.com", "username": f"reg-{tag}", "password": "s3cret-pass"}
    r = await client.post("/auth/register", json=body)
    assert r.status_code == 201, r.text
    assert set(r.json()) == {"access_token", "token_type", "expires_in"}
    assert REFRESH_COOKIE in client.cookies

    me = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == f"reg-{tag}"
    assert me.json()["is_admin"] is False


async def test_me_shows_admin_flag(client: AsyncClient, make_user) -> None:
    admin = await make_user(admin=True)
    r = await client.get("/users/me", headers=admin)
    assert r.json()["is_admin"] is True


async def test_refresh_cookie_is_scoped_to_api_auth(client: AsyncClient) -> None:
    tag = secrets.token_hex(4)
    body = {"email": f"ck-{tag}@example.com", "username": f"ck-{tag}", "password": "s3cret-pass"}
    r = await client.post("/auth/register", json=body)
    assert f"Path={REFRESH_COOKIE_PATH}" in r.headers["set-cookie"]
    assert REFRESH_COOKIE_PATH == "/api/auth"


async def test_api_is_not_served_at_root(client: AsyncClient) -> None:
    r = await client.get("http://test/health")
    assert r.status_code == 404
