from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.exceptions import UserAlreadyExistsError
from app.db.config import SessionDep
from app.db.models.user import User
from app.schemas.auth import UserCreate, UserLoginSchema, UserRead
from app.schemas.tokens import TokenPairSchema
from app.services.auth import authenticate_user, register_user
from app.services.tokens import issue_token_pair

router = APIRouter(prefix="/auth", tags=["auth"])

_401 = {status.HTTP_401_UNAUTHORIZED: {"description": "Incorrect email or password"}}


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    responses={status.HTTP_409_CONFLICT: {"description": "Email or username already exists"}},
)
async def register(user_data: UserCreate, session: SessionDep) -> User:
    try:
        return await register_user(session, user_data)
    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from None


@router.post(
    "/login", 
    response_model=TokenPairSchema, 
    summary="Log in with JSON", 
    responses=_401
)
async def login_json(data: UserLoginSchema, session: SessionDep) -> TokenPairSchema:
    user = await authenticate_user(session, data.email, data.password)
    if user is None:
        raise _invalid_credentials()
    return await issue_token_pair(session, user.id)


@router.post(
    "/token",
    response_model=TokenPairSchema,
    summary="Log in with form data (used by the Authorize button in /docs)",
    responses=_401,
)
async def login_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], 
    session: SessionDep
) -> TokenPairSchema:
    user = await authenticate_user(session, form.username, form.password)
    if user is None:
        raise _invalid_credentials()
    return await issue_token_pair(session, user.id)


@router.post("/login/OAuth/2.0")
async def login_oauth():
    pass
