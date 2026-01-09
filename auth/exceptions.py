"""Typed exceptions for auth failures."""


class AuthError(Exception):
    """Base class for authentication/authorization errors."""


class InvalidTokenError(AuthError):
    """
    Token is invalid, expired, or already used.

    Used for both magic link tokens and session tokens.
    """


class RateLimitedError(AuthError):
    """Too many attempts. Client should wait before retrying."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limited. Retry after {retry_after_seconds} seconds.")


class UserNotFoundError(AuthError):
    """
    Email not associated with any user.

    Note: In user-facing responses, don't reveal whether email exists.
    This exception is for internal logic only.
    """


class SessionExpiredError(AuthError):
    """Session has expired and user must re-authenticate."""


class SessionRevokedError(AuthError):
    """Session was explicitly revoked (logout or security action)."""


class UserInactiveError(AuthError):
    """User account is deactivated. Login not permitted."""
