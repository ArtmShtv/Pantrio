import re
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InactiveUserError,
    OAuthAccountConflictError,
    OAuthEmailNotVerifiedError,
)
from app.db.models.enums import AuthProvider
from app.db.models.user import SocialAccount, User
from app.services.user import get_user_by_email, normalize_email


@dataclass(frozen=True)
class OAuthIdentity:
    """What we keep from the provider's verified ID token."""

    provider: AuthProvider
    subject: str  # the provider's stable user ID ("sub"); never changes
    email: str | None
    email_verified: bool


async def login_with_oauth(session: AsyncSession, identity: OAuthIdentity) -> User:
    """Return the local user for this provider identity, creating or linking one.

    1. Known identity (provider + sub already linked): log that user in.
    2. Unknown identity, email matches a user with a verified email: link it.
    3. Unknown identity, no user with that email: create one (no password).
    """
    user = await _get_user_by_identity(session, identity)
    if user is None:
        try:
            user = await _link_or_create(session, identity)
            await session.commit()
        except IntegrityError:
            # Two callbacks for the same new identity raced (e.g. a double
            # click). The other one won; its row is now there, so use it.
            await session.rollback()
            user = await _get_user_by_identity(session, identity)
            if user is None:
                raise

    if not user.is_active:
        raise InactiveUserError
    return user


async def _get_user_by_identity(session: AsyncSession, identity: OAuthIdentity) -> User | None:
    # Look up by (provider, sub), never by email: the email on a Google
    # account can change, the sub can't.
    return await session.scalar(
        select(User)
        .join(SocialAccount)
        .where(
            SocialAccount.provider == identity.provider,
            SocialAccount.provider_user_id == identity.subject,
        )
    )


async def _link_or_create(session: AsyncSession, identity: OAuthIdentity) -> User:
    if not identity.email or not identity.email_verified:
        # Without a verified email we can't tell whose account this should be.
        raise OAuthEmailNotVerifiedError

    email = normalize_email(identity.email)
    user = await get_user_by_email(session, email)

    if user is None:
        user = User(
            email=email,
            username=await _free_username(session, email),
            password_hash=None,  # this user can only log in through the provider
            email_verified=True,  # the provider just proved it
        )
        session.add(user)
        await session.flush()  # assigns user.id for the SocialAccount below
    elif not user.email_verified:
        # Someone registered this email with a password but never proved they
        # own it. If we linked, that person's password would keep working on
        # the real owner's account ("pre-account takeover"). Refuse instead.
        raise OAuthAccountConflictError

    session.add(
        SocialAccount(
            user_id=user.id,
            provider=identity.provider,
            provider_user_id=identity.subject,
            email_at_provider=email,
        )
    )
    await session.flush()  # surfaces a unique-constraint race here, inside the try
    return user


_NOT_ALLOWED = re.compile(r"[^a-z0-9_.-]")


async def _free_username(session: AsyncSession, email: str) -> str:
    """Derive a username from the email's local part, adding a suffix if taken."""
    base = _NOT_ALLOWED.sub("", email.split("@", 1)[0])[:40]
    if len(base) < 3:
        base = "user"
    candidates = [base] + [f"{base}-{secrets.token_hex(3)}" for _ in range(5)]
    for candidate in candidates:
        taken = await session.scalar(select(User.id).where(User.username == candidate))
        if taken is None:
            return candidate
    raise RuntimeError("could not find a free username")
