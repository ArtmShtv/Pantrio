class UserAlreadyExistsError(Exception):
    pass


class OAuthEmailNotVerifiedError(Exception):
    """The provider did not confirm that the user owns this email address."""


class OAuthAccountConflictError(Exception):
    """A password account with this email exists, but its email isn't verified.

    Linking it automatically would let whoever registered that account first
    (possibly not the mailbox owner) keep access via the password.
    """


class InactiveUserError(Exception):
    pass


class NotFoundError(Exception):
    """The row doesn't exist or isn't visible to this user (-> 404)."""


class PermissionDeniedError(Exception):
    """The row is visible but this user may not change it (-> 403)."""


class ConflictError(Exception):
    """The change clashes with existing data (-> 409)."""


class DomainValidationError(Exception):
    """Input is well-formed but breaks a business rule (-> 422)."""
