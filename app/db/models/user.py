"""Auth models: users and linked OAuth accounts (refresh tokens: refresh_token.py)."""

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, created_at, int_pk, updated_at
from app.db.models.enums import AuthProvider, str_enum


class User(Base):
    id: Mapped[int_pk]
    # Stored lowercased (the CHECK enforces it), so the plain unique constraint
    # is effectively case-insensitive: "Artem@x.ru" and "artem@x.ru" collide.
    # Normalize in the service layer before insert/lookup.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    # NULL for users who only ever logged in through OAuth.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    # Gate for auto-linking an OAuth login to this account by email.
    email_verified: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Only admins may create/edit global ingredients and meals (created_by IS NULL).
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=false())

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    # lazy="raise": with async sessions an implicit lazy load fails with a
    # confusing MissingGreenlet error. "raise" fails immediately with a clear
    # message instead, forcing an explicit selectinload() in the query.
    # passive_deletes: let ON DELETE CASCADE in Postgres remove children
    # instead of the ORM loading and deleting them one by one.
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
    # The provider's stable ID ("sub" in OIDC). Never key on email: it can change.
    provider_user_id: Mapped[str] = mapped_column(String(255))
    # For debugging/support only; not used for lookups.
    email_at_provider: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[created_at]

    user: Mapped[User] = relationship(back_populates="social_accounts", lazy="raise")

    __table_args__ = (
        # One provider identity belongs to exactly one user.
        UniqueConstraint("provider", "provider_user_id"),
        # One account per provider per user: no linking two Google accounts.
        UniqueConstraint("user_id", "provider"),
    )
