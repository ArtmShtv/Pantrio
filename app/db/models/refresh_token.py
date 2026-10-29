import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, created_at, int_pk


class RefreshToken(Base):
    """One row per issued refresh token. Table name: refresh_tokens.

    A family is one login session on one device. /auth/refresh marks the
    presented token as used and issues a new one in the same family.
    If an already-used token comes back, someone kept a copy of it (theft or
    replay): we can't tell the real user from the thief, so the whole family
    is revoked and that device has to log in again.
    """

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # SHA-256 hex of the raw token; the raw value only ever exists in the cookie.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at]
