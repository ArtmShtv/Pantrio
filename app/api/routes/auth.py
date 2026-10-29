from fastapi import APIRouter, HTTPException, status

from app.core.exceptions import UserAlreadyExistsError
from app.db.config import SessionDep
from app.db.models.user import User
from app.schemas.auth import UserCreate, UserRead, UserLoginSchema
from app.schemas.tokens import TokenPairSchema
from app.services.auth import register_user, authenticate_user
from app.services.tokens import create_access_token, create_refresh_token

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password",
    headers={"WWW-Authenticate": "Bearer"},
)

def _issue_tokens(user: User) -> TokenPairSchema:
    return TokenPairSchema(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
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
    #dependencies=[Depends(limit_login_attempts)],
    responses={429: {"description": "Too many login attempts"}},
)
async def login_json(data: UserLoginSchema, session: SessionDep):
    user = await authenticate_user(session, data.email, data.password)
    if not user:
        raise _INVALID_CREDENTIALS
    return _issue_tokens(user)


@router.post("/login/OAuth/2.0")
async def login_oauth():
    pass