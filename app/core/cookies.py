from starlette.responses import Response

from app.core.config import get_settings
from app.core.security import refresh_ttl

REFRESH_COOKIE = "refresh_token"
_PATH = "/auth"


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw_token,
        max_age=int(refresh_ttl().total_seconds()),
        path=_PATH,
        httponly=True,
        secure=get_settings().ENVIRONMENT == "production",
        samesite="lax",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path=_PATH,
        httponly=True,
        secure=get_settings().ENVIRONMENT == "production",
        samesite="lax",
    )
