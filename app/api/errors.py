from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)

_STATUS = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    ConflictError: status.HTTP_409_CONFLICT,
    DomainValidationError: 422,
}


def register_exception_handlers(app: FastAPI) -> None:
    for exc_class, code in _STATUS.items():

        async def handler(_: Request, exc: Exception, code: int = code) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=code)

        app.add_exception_handler(exc_class, handler)
