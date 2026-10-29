from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, CurrentUser
from app.db.models.user import User
from app.schemas.auth import UserReadSchema, UserUpdateSchema

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserReadSchema)
async def read_me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserReadSchema)
async def update_me(payload: UserUpdateSchema, user: CurrentUser, db: DB):
    changes = payload.model_dump(exclude_unset=True)

    if "username" in changes:
        taken = await db.scalar(
            select(User.id).where(
                func.lower(User.username) == changes["username"].lower(),
                User.id != user.id,
            )
        )
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken") from None

    for field, value in changes.items():
        setattr(user, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken") from None

    await db.refresh(user)
    return user
