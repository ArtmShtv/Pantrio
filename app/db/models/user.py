from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, created_at, int_pk, updated_at
from app.db.models.enums import AuthProvider, str_enum


class User(Base):
    id: Mapped[int_pk]
    email: Mapped[str] = mapped_column(String(320), unique=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))

    email_verified: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=false())

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, username={self.username!r})"


class SocialAccount(Base):
    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[AuthProvider] = mapped_column(str_enum(AuthProvider, "provider"))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    email_at_provider: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[created_at]

    user: Mapped[User] = relationship(back_populates="social_accounts", lazy="raise")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id"),
        UniqueConstraint("user_id", "provider"),
    )
