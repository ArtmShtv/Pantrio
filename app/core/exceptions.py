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
