"""Tests for auth/config.py - Auth configuration with validation."""

import pytest
from pydantic import ValidationError

from auth.config import AuthConfig


class TestAuthConfigDefaults:
    """Tests that AuthConfig has sensible defaults."""

    def test_magic_link_expiry_default(self):
        config = AuthConfig()
        assert config.magic_link_expiry_minutes == 10

    def test_session_expiry_default(self):
        config = AuthConfig()
        assert config.session_expiry_hours == 2160  # 90 days

    def test_rate_limit_defaults(self):
        config = AuthConfig()
        assert config.rate_limit_attempts == 5
        assert config.rate_limit_window_minutes == 15


class TestAuthConfigValidation:
    """Tests that AuthConfig enforces validation bounds."""

    def test_magic_link_expiry_min_bound(self):
        with pytest.raises(ValidationError):
            AuthConfig(magic_link_expiry_minutes=4)  # < 5

    def test_magic_link_expiry_max_bound(self):
        with pytest.raises(ValidationError):
            AuthConfig(magic_link_expiry_minutes=61)  # > 60

    def test_session_expiry_min_bound(self):
        with pytest.raises(ValidationError):
            AuthConfig(session_expiry_hours=0)  # < 1

    def test_session_expiry_max_bound(self):
        with pytest.raises(ValidationError):
            AuthConfig(session_expiry_hours=2161)  # > 2160 (90 days)
