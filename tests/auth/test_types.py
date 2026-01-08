"""Tests for auth/types.py - Pydantic models for auth domain."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from auth.types import (
    User,
    MagicLinkRequest,
    MagicLinkToken,
)


class TestUserValidation:
    """Tests that User model rejects invalid data."""

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            User(
                id=uuid4(),
                email="not-an-email",
                created_at=datetime.now(timezone.utc),
            )

    def test_rejects_missing_id(self):
        with pytest.raises(ValidationError):
            User(
                email="test@example.com",
                created_at=datetime.now(timezone.utc),
            )

    def test_rejects_missing_email(self):
        with pytest.raises(ValidationError):
            User(
                id=uuid4(),
                created_at=datetime.now(timezone.utc),
            )

    def test_last_login_defaults_to_none(self):
        user = User(
            id=uuid4(),
            email="test@example.com",
            created_at=datetime.now(timezone.utc),
        )
        assert user.last_login_at is None


class TestMagicLinkRequestValidation:
    """Tests that MagicLinkRequest rejects invalid data."""

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            MagicLinkRequest(email="not-an-email")


class TestMagicLinkTokenValidation:
    """Tests that MagicLinkToken requires explicit used state (fail closed)."""

    def test_rejects_missing_used(self):
        """Token must explicitly declare its used state."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            MagicLinkToken(
                token="abc123",
                user_id=uuid4(),
                email="test@example.com",
                created_at=now,
                expires_at=now,
                # used not specified - should fail
            )
