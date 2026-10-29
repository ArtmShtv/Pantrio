from typing import Annotated

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from joserfc.errors import JoseError

from app.auth.oauth import get_oauth_client
from app.core.exceptions import (
    InactiveUserError,
    OAuthAccountConflictError,
    OAuthEmailNotVerifiedError,
    UserAlreadyExistsError,
)
from app.db.config import SessionDep
from app.db.models.enums import AuthProvider
from app.db.models.user import User
from app.schemas.auth import UserCreateSchema, UserLoginSchema, UserReadSchema
from app.schemas.tokens import TokenPairSchema
from app.services.auth import authenticate_user, register_user
from app.services.oauth import OAuthIdentity, login_with_oauth
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
    response_model=UserReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    responses={status.HTTP_409_CONFLICT: {"description": "Email or username already exists"}},
)
async def register(user_data: UserCreateSchema, session: SessionDep) -> User:
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


def _oauth_client_or_501(provider: AuthProvider):
    client = get_oauth_client(provider)
    if client is None:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, f"{provider} login is not configured"
        )
    return client


@router.get(
    "/{provider}/login",
    summary="Start OAuth login (open in a browser, not via fetch)",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "Provider not configured"}},
)
async def oauth_login(provider: AuthProvider, request: Request):
    client = _oauth_client_or_501(provider)
    redirect_uri = request.url_for("oauth_callback", provider=provider.value)
    return await client.authorize_redirect(request, str(redirect_uri))


@router.get(
    "/{provider}/callback",
    response_model=TokenPairSchema,
    summary="OAuth callback (the provider redirects here)",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Login failed or email not verified"},
        status.HTTP_403_FORBIDDEN: {"description": "Account is disabled"},
        status.HTTP_409_CONFLICT: {"description": "Email belongs to a password account"},
    },
)
async def oauth_callback(
    provider: AuthProvider, request: Request, session: SessionDep
) -> TokenPairSchema:
    client = _oauth_client_or_501(provider)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{provider} login failed: {e.error}"
        ) from None
    except JoseError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{provider} login failed: invalid ID token"
        ) from None

    claims = token.get("userinfo")
    if not claims or "sub" not in claims:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{provider} returned no identity")

    identity = OAuthIdentity(
        provider=provider,
        subject=str(claims["sub"]),
        email=claims.get("email"),
        email_verified=claims.get("email_verified") is True,
    )
    try:
        user = await login_with_oauth(session, identity)
    except OAuthEmailNotVerifiedError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Your {provider} email address is not verified"
        ) from None
    except OAuthAccountConflictError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists. Log in with your password.",
        ) from None
    except InactiveUserError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled") from None

    return await issue_token_pair(session, user.id)
