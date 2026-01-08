"""Tests for auth/exceptions.py - Typed exceptions for auth failures."""

import pytest

from auth.exceptions import (
    AuthError,
    InvalidTokenError,
    RateLimitedError,
    UserNotFoundError,
    SessionExpiredError,
    SessionRevokedError,
)


class TestExceptionInheritance:
    """All auth exceptions should inherit from AuthError."""

    def test_invalid_token_inherits(self):
        assert issubclass(InvalidTokenError, AuthError)

    def test_rate_limited_inherits(self):
        assert issubclass(RateLimitedError, AuthError)

    def test_user_not_found_inherits(self):
        assert issubclass(UserNotFoundError, AuthError)

    def test_session_expired_inherits(self):
        assert issubclass(SessionExpiredError, AuthError)

    def test_session_revoked_inherits(self):
        assert issubclass(SessionRevokedError, AuthError)


class TestRateLimitedError:
    """RateLimitedError should carry retry timing info."""

    def test_stores_retry_seconds(self):
        """retry_after_seconds should be accessible."""
        err = RateLimitedError(30)
        assert err.retry_after_seconds == 30

    def test_message_includes_seconds(self):
        """Error message should include the retry time."""
        err = RateLimitedError(45)
        assert "45" in str(err)

    def test_can_be_caught_as_auth_error(self):
        """Should be catchable as AuthError."""
        with pytest.raises(AuthError):
            raise RateLimitedError(10)
