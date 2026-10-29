from fastapi import APIRouter, HTTPException, status

from app.core.exceptions import UserAlreadyExistsError
from app.db.config import SessionDep
from app.db.models.user import User
from app.schemas.auth import UserCreate, UserRead
from app.services.auth import register_user

router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.post("/login/OAuth/2.0")
async def login_oauth():
    pass


@router.post("/login")
async def login_basic():
    pass
