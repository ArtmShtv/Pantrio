from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.db.config import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Pantrio", lifespan=lifespan)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SESSION_SECRET.get_secret_value(),
        https_only=settings.ENVIRONMENT == "production",
        same_site="lax",
    )

    app.include_router(api_router)
    return app


app = create_app()
