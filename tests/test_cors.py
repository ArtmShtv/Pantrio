from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.main import create_app

FRONTEND = "https://pantrio.example"


@pytest.fixture
def cors_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CORS_ORIGINS", f"{FRONTEND}/, https://other.example")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CORS_ORIGINS")
    get_settings.cache_clear()


def test_origins_are_split_and_normalised(cors_settings) -> None:
    assert get_settings().CORS_ORIGINS == [FRONTEND, "https://other.example"]


def test_wildcard_origin_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValidationError):
        Settings()


async def test_preflight_from_allowed_origin(cors_settings) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.options(
            "/api/auth/refresh",
            headers={"Origin": FRONTEND, "Access-Control-Request-Method": "POST"},
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == FRONTEND
    assert r.headers["access-control-allow-credentials"] == "true"


async def test_unknown_origin_gets_no_cors_headers(cors_settings) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


async def test_no_cors_middleware_without_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "")
    get_settings.cache_clear()
    try:
        app = create_app()
    finally:
        get_settings.cache_clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/health", headers={"Origin": FRONTEND})
    assert "access-control-allow-origin" not in r.headers
