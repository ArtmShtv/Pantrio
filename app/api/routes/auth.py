"""Auth endpoints.

Token flow:
- /login, /token and the OAuth callback start a session: the access token is
  returned in the JSON body, the refresh token is set as an httpOnly cookie.
- The client keeps the access token in memory and sends it as
  `Authorization: Bearer ...`. When it expires (401), the client calls
  /refresh; the browser attaches the cookie automatically.
- /logout revokes the session and clears the cookie.
"""

from typing import Annotated

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from joserfc.errors import JoseError

from app.auth.oauth import get_oauth_client
from app.core.cookies import REFRESH_COOKIE, clear_refresh_cookie, set_refresh_cookie
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
from app.schemas.tokens import TokenResponse
from app.services.auth import authenticate_user, register_user
from app.services.oauth import OAuthIdentity, login_with_oauth
from app.services.sessions import InvalidRefreshToken, revoke_session, rotate_refresh_token
from app.services.tokens import issue_tokens, token_response

router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]

_401 = {status.HTTP_401_UNAUTHORIZED: {"description": "Incorrect email or password"}}


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _start_session(session: SessionDep, response: Response, user_id: int) -> TokenResponse:
    body, raw_refresh = await issue_tokens(session, user_id)
    set_refresh_cookie(response, raw_refresh)
    return body


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


@router.post("/login", response_model=TokenResponse, summary="Log in with JSON", responses=_401)
async def login_json(
    data: UserLoginSchema, session: SessionDep, response: Response
) -> TokenResponse:
    user = await authenticate_user(session, data.email, data.password)
    if user is None:
        raise _invalid_credentials()
    return await _start_session(session, response, user.id)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Log in with form data (used by the Authorize button in /docs)",
    responses=_401,
)
async def login_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    response: Response,
) -> TokenResponse:
    # The OAuth2 form field is called "username"; we treat it as the email.
    user = await authenticate_user(session, form.username, form.password)
    if user is None:
        raise _invalid_credentials()
    return await _start_session(session, response, user.id)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Get a new access token using the refresh cookie",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid refresh token"}},
)
async def refresh(session: SessionDep, response: Response, refresh_token: RefreshCookie = None):
    try:
        if not refresh_token:
            raise InvalidRefreshToken
        user, new_raw = await rotate_refresh_token(session, refresh_token)
    except InvalidRefreshToken:
        # Return (not raise) so we can also wipe the dead cookie: cookies set
        # on `response` are discarded when an HTTPException is raised.
        error = JSONResponse(
            {"detail": "Invalid refresh token"}, status_code=status.HTTP_401_UNAUTHORIZED
        )
        clear_refresh_cookie(error)
        return error

    set_refresh_cookie(response, new_raw)
    return token_response(user.id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
async def logout(session: SessionDep, refresh_token: RefreshCookie = None) -> Response:
    # No access token required: it may already be expired when the user logs out.
    # Idempotent: logging out twice, or with no cookie, is still a 204.
    if refresh_token:
        await revoke_session(session, refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response)
    return response


def _oauth_client_or_501(provider: AuthProvider):
    client = get_oauth_client(provider)
    if client is None:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"{provider} login is not configured")
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
    response_model=TokenResponse,
    summary="OAuth callback (the provider redirects here)",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Login failed or email not verified"},
        status.HTTP_403_FORBIDDEN: {"description": "Account is disabled"},
        status.HTTP_409_CONFLICT: {"description": "Email belongs to a password account"},
    },
)
async def oauth_callback(
    provider: AuthProvider, request: Request, session: SessionDep, response: Response
) -> TokenResponse:
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

    return await _start_session(session, response, user.id)
