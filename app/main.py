"""App entry point. Run with: uv run fastapi dev app/main.py"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Code before `yield` runs at startup, after it at shutdown.
    yield
    # Close pooled connections cleanly so Postgres doesn't see them dropped.
    await engine.dispose()


def create_app() -> FastAPI:
    """App factory: building the app in a function, not at import time, lets
    tests create a fresh app (e.g. with different settings) when they need to."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Authlib keeps the OAuth `state` / PKCE verifier in this signed cookie
    # between the redirect to Google/Yandex/VK and the callback. It is NOT used
    # for API auth: that is the JWT in the Authorization header.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        https_only=settings.environment == "production",
        same_site="lax",  # must be lax: the OAuth callback is a cross-site redirect
    )

    app.include_router(api_router)
    return app


app = create_app()
