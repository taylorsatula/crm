"""Tests for SessionManager - session token lifecycle."""

import pytest

from auth.session import SessionManager
from auth.config import AuthConfig
from auth.exceptions import SessionExpiredError


@pytest.fixture
def config():
    """Test config with short session for testing."""
    return AuthConfig(
        session_expiry_hours=1,
    )


@pytest.fixture
def session_manager(valkey, config):
    """SessionManager with test config."""
    manager = SessionManager(valkey, config)
    yield manager
    # Cleanup session keys
    for key in valkey._client.keys("session:*"):
        valkey._client.delete(key)


class TestCreateSession:
    """Test session creation."""

    def test_returns_session_with_token(self, session_manager, test_user_id):
        """Created session has non-empty token."""
        session = session_manager.create_session(test_user_id)

        assert session.token
        assert len(session.token) > 20

    def test_session_has_correct_user_id(self, session_manager, test_user_id):
        """Session contains the user_id it was created for."""
        session = session_manager.create_session(test_user_id)

        assert session.user_id == test_user_id

    def test_different_users_get_different_tokens(self, session_manager, test_user_id, test_user_b_id):
        """Different users get unique tokens."""
        session_a = session_manager.create_session(test_user_id)
        session_b = session_manager.create_session(test_user_b_id)

        assert session_a.token != session_b.token
        assert session_a.user_id == test_user_id
        assert session_b.user_id == test_user_b_id


class TestValidateSession:
    """Test session validation."""

    def test_valid_session_returns_session(self, session_manager, test_user_id):
        """Valid token returns the session."""
        created = session_manager.create_session(test_user_id)

        validated = session_manager.validate_session(created.token)

        assert validated.user_id == test_user_id
        assert validated.token == created.token

    def test_invalid_token_raises(self, session_manager):
        """Invalid token raises SessionExpiredError."""
        with pytest.raises(SessionExpiredError):
            session_manager.validate_session("nonexistent-token")

    def test_revoked_session_raises(self, session_manager, test_user_id):
        """Revoked session raises SessionExpiredError."""
        session = session_manager.create_session(test_user_id)
        session_manager.revoke_session(session.token)

        with pytest.raises(SessionExpiredError):
            session_manager.validate_session(session.token)


class TestRevokeSession:
    """Test session revocation."""

    def test_revoke_removes_session(self, session_manager, test_user_id):
        """Revoked session cannot be validated."""
        session = session_manager.create_session(test_user_id)
        session_manager.revoke_session(session.token)

        with pytest.raises(SessionExpiredError):
            session_manager.validate_session(session.token)

    def test_revoke_nonexistent_does_not_error(self, session_manager):
        """Revoking nonexistent token doesn't raise."""
        session_manager.revoke_session("never-existed")


class TestSessionSlidingWindow:
    """Test session TTL resets on every validation (sliding window)."""

    def test_validation_resets_expiry(self, session_manager, test_user_id):
        """Each validation resets expiry to full duration."""
        import time

        session = session_manager.create_session(test_user_id)
        original_expires = session.expires_at

        # Small delay to ensure time passes
        time.sleep(0.01)

        validated = session_manager.validate_session(session.token)

        # Expiry should be pushed forward
        assert validated.expires_at > original_expires
        assert validated.last_activity_at > session.last_activity_at

    def test_multiple_validations_keep_extending(self, session_manager, test_user_id):
        """Multiple validations keep pushing expiry forward."""
        import time

        session = session_manager.create_session(test_user_id)

        for _ in range(3):
            time.sleep(0.01)
            previous_expires = session.expires_at
            session = session_manager.validate_session(session.token)
            assert session.expires_at > previous_expires
