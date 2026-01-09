"""Tests for AuthService - core auth orchestration."""

import secrets
from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID

import pytest

from auth.service import AuthService, MagicLinkResult
from auth.database import AuthDatabase
from auth.session import SessionManager
from auth.rate_limiter import RateLimiter
from auth.security_logger import SecurityLogger
from auth.config import AuthConfig
from auth.types import AuthenticatedUser
from auth.exceptions import (
    RateLimitedError,
    InvalidTokenError,
    UserInactiveError,
    SessionExpiredError,
)
from clients.email_client import EmailGatewayClient, EmailGatewayError
from utils.timezone import now_utc


@pytest.fixture
def config():
    """Test config with short expiry for faster tests."""
    return AuthConfig(
        magic_link_expiry_minutes=5,
        session_expiry_hours=1,
        rate_limit_attempts=3,
        rate_limit_window_minutes=5,
        app_base_url="https://test.example.com",
    )


@pytest.fixture
def mock_email_client():
    """Mock email client - no actual emails sent in tests."""
    mock = Mock(spec=EmailGatewayClient)
    mock.send_magic_link.return_value = None
    return mock


@pytest.fixture
def auth_service(db, valkey, config, mock_email_client):
    """AuthService with real DB/Valkey but mocked email."""
    auth_db = AuthDatabase(db)
    session_manager = SessionManager(valkey, config)
    rate_limiter = RateLimiter(valkey, config)
    security_logger = SecurityLogger(db)

    service = AuthService(
        config=config,
        auth_db=auth_db,
        session_manager=session_manager,
        rate_limiter=rate_limiter,
        email_client=mock_email_client,
        security_logger=security_logger,
    )

    yield service

    # Cleanup Valkey keys
    for key in valkey._client.keys("ratelimit:*"):
        valkey._client.delete(key)
    for key in valkey._client.keys("session:*"):
        valkey._client.delete(key)
    for key in valkey._client.keys("enumeration:*"):
        valkey._client.delete(key)


@pytest.fixture
def cleanup_user(db_admin):
    """Track users created during tests for cleanup."""
    created_emails = []

    def _track(email):
        created_emails.append(email.lower())

    yield _track

    for email in created_emails:
        db_admin.execute("DELETE FROM users WHERE email = %s", (email,))


@pytest.fixture
def cleanup_security_events(db_admin):
    """Clean up security events after test."""
    yield
    db_admin.execute(
        "DELETE FROM security_events WHERE email LIKE '%@authtest.example.com'"
    )


class TestRequestMagicLink:
    """Test magic link request flow."""

    def test_existing_user_sends_magic_link(
        self, db_admin, auth_service, mock_email_client, cleanup_user, cleanup_security_events
    ):
        """Existing user gets magic link sent."""
        cleanup_user("existing@authtest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("existing@authtest.example.com",),
        )

        result = auth_service.request_magic_link(
            email="existing@authtest.example.com",
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        assert result.sent is True
        assert result.needs_signup is False
        mock_email_client.send_magic_link.assert_called_once()
        call_args = mock_email_client.send_magic_link.call_args
        assert call_args.kwargs["email"] == "existing@authtest.example.com"
        assert len(call_args.kwargs["token"]) > 20

    def test_nonexistent_email_returns_needs_signup(
        self, auth_service, mock_email_client, cleanup_security_events
    ):
        """Non-existent email returns needs_signup indicator, no email sent."""
        result = auth_service.request_magic_link(
            email="unknown@authtest.example.com",
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        assert result.sent is False
        assert result.needs_signup is True
        mock_email_client.send_magic_link.assert_not_called()

    def test_rate_limited_after_max_attempts_per_email(
        self, db_admin, auth_service, config, cleanup_user, cleanup_security_events
    ):
        """Exceeding per-email rate limit raises RateLimitedError."""
        cleanup_user("ratelimit@authtest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("ratelimit@authtest.example.com",),
        )

        for _ in range(config.rate_limit_attempts):
            auth_service.request_magic_link(
                email="ratelimit@authtest.example.com",
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

        with pytest.raises(RateLimitedError) as exc_info:
            auth_service.request_magic_link(
                email="ratelimit@authtest.example.com",
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

        assert exc_info.value.retry_after_seconds > 0

    def test_enumeration_lockout_after_multiple_unknown_emails(
        self, auth_service, mock_email_client, cleanup_security_events
    ):
        """IP locked out after 3+ non-existent email attempts."""
        ip = "10.0.0.50"

        # First 3 attempts for unknown emails should return needs_signup
        for i in range(3):
            result = auth_service.request_magic_link(
                email=f"unknown{i}@authtest.example.com",
                ip_address=ip,
                user_agent="TestBrowser/1.0",
            )
            assert result.needs_signup is True

        # 4th attempt should be rate limited
        with pytest.raises(RateLimitedError):
            auth_service.request_magic_link(
                email="unknown99@authtest.example.com",
                ip_address=ip,
                user_agent="TestBrowser/1.0",
            )

    def test_enumeration_counter_not_incremented_for_existing_user(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events, valkey
    ):
        """Existing user lookups don't count toward enumeration limit."""
        cleanup_user("realuser@authtest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("realuser@authtest.example.com",),
        )
        ip = "10.0.0.51"

        # Request magic link for existing user
        auth_service.request_magic_link(
            email="realuser@authtest.example.com",
            ip_address=ip,
            user_agent="TestBrowser/1.0",
        )

        # Enumeration counter should NOT exist for this IP
        enum_key = f"enumeration:{ip}"
        count = valkey.get(enum_key)
        assert count is None

    def test_enumeration_lockout_resets_on_successful_login(
        self, db_admin, auth_service, mock_email_client, cleanup_user, cleanup_security_events
    ):
        """Successful login resets enumeration counter for that IP."""
        cleanup_user("realuser2@authtest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("realuser2@authtest.example.com",),
        )
        ip = "10.0.0.52"

        # Use up 2 enumeration attempts
        for i in range(2):
            auth_service.request_magic_link(
                email=f"fake{i}@authtest.example.com",
                ip_address=ip,
                user_agent="TestBrowser/1.0",
            )

        # Now do a successful login flow
        row = db_admin.execute_single(
            "SELECT id FROM users WHERE email = %s",
            ("realuser2@authtest.example.com",),
        )
        user_id = row["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "realuser2@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        auth_service.verify_magic_link(
            token=token,
            ip_address=ip,
            user_agent="TestBrowser/1.0",
        )

        # Enumeration counter should be reset - can try 3 more unknown emails
        for i in range(3):
            result = auth_service.request_magic_link(
                email=f"afterlogin{i}@authtest.example.com",
                ip_address=ip,
                user_agent="TestBrowser/1.0",
            )
            assert result.needs_signup is True

    def test_logs_security_event_for_existing_user(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Magic link request for existing user creates security event."""
        cleanup_user("logged@authtest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("logged@authtest.example.com",),
        )

        auth_service.request_magic_link(
            email="logged@authtest.example.com",
            ip_address="10.0.0.1",
            user_agent="TestAgent",
        )

        event = db_admin.execute_single(
            """SELECT event_type, email, ip_address
               FROM security_events
               WHERE email = %s AND event_type = 'magic_link_requested'
               ORDER BY created_at DESC LIMIT 1""",
            ("logged@authtest.example.com",),
        )
        assert event is not None
        assert str(event["ip_address"]) == "10.0.0.1"

    def test_email_failure_propagates(
        self, db_admin, auth_service, mock_email_client, cleanup_user, cleanup_security_events
    ):
        """Email gateway failure raises EmailGatewayError."""
        cleanup_user("emailfail@authtest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("emailfail@authtest.example.com",),
        )
        mock_email_client.send_magic_link.side_effect = EmailGatewayError(
            "Connection failed"
        )

        with pytest.raises(EmailGatewayError):
            auth_service.request_magic_link(
                email="emailfail@authtest.example.com",
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )


class TestVerifyMagicLink:
    """Test magic link verification flow."""

    def test_valid_token_returns_authenticated_user(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Valid, unused, unexpired token returns AuthenticatedUser."""
        cleanup_user("verify@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("verify@authtest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "verify@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        result = auth_service.verify_magic_link(
            token=token,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        assert isinstance(result, AuthenticatedUser)
        assert result.user.email == "verify@authtest.example.com"
        assert result.session.token is not None
        assert len(result.session.token) > 20

    def test_already_used_token_raises(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Already-used token raises InvalidTokenError."""
        cleanup_user("used@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("used@authtest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, true) RETURNING token""",
            (token, user_id, "used@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        with pytest.raises(InvalidTokenError):
            auth_service.verify_magic_link(
                token=token,
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

    def test_expired_token_raises(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Expired token raises InvalidTokenError."""
        cleanup_user("expired@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("expired@authtest.example.com",),
        )
        user_id = result[0]["id"]

        past = now_utc() - timedelta(hours=1)
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "expired@authtest.example.com", past - timedelta(minutes=10), past),
        )

        with pytest.raises(InvalidTokenError):
            auth_service.verify_magic_link(
                token=token,
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

    def test_nonexistent_token_raises(self, auth_service, cleanup_security_events):
        """Nonexistent token raises InvalidTokenError."""
        with pytest.raises(InvalidTokenError):
            auth_service.verify_magic_link(
                token="nonexistent-token-xyz",
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

    def test_inactive_user_raises(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Inactive user cannot verify magic link."""
        cleanup_user("deactivated@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email, is_active) VALUES (%s, false) RETURNING id",
            ("deactivated@authtest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "deactivated@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        with pytest.raises(UserInactiveError):
            auth_service.verify_magic_link(
                token=token,
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

    def test_marks_token_used_after_verification(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Token is marked used after successful verification."""
        cleanup_user("markused@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("markused@authtest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "markused@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        auth_service.verify_magic_link(
            token=token,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        row = db_admin.execute_single(
            "SELECT used FROM magic_link_tokens WHERE token = %s",
            (token,),
        )
        assert row["used"] is True

    def test_updates_last_login(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Successful verification updates user's last_login_at."""
        cleanup_user("lastlogin@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("lastlogin@authtest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "lastlogin@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        before = now_utc()
        auth_service.verify_magic_link(
            token=token,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )
        after = now_utc()

        row = db_admin.execute_single(
            "SELECT last_login_at FROM users WHERE id = %s",
            (str(user_id),),
        )
        assert row["last_login_at"] is not None
        assert before <= row["last_login_at"] <= after

    def test_resets_rate_limit_on_success(
        self, db_admin, auth_service, config, mock_email_client, cleanup_user, cleanup_security_events
    ):
        """Successful verification resets per-email rate limit."""
        cleanup_user("resetrate@authtest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("resetrate@authtest.example.com",),
        )

        # Use some rate limit attempts
        for _ in range(config.rate_limit_attempts - 1):
            auth_service.request_magic_link(
                email="resetrate@authtest.example.com",
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

        row = db_admin.execute_single(
            "SELECT id FROM users WHERE email = %s",
            ("resetrate@authtest.example.com",),
        )
        user_id = row["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "resetrate@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        auth_service.verify_magic_link(
            token=token,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        # Should be able to make full quota of new requests
        mock_email_client.reset_mock()
        for _ in range(config.rate_limit_attempts):
            auth_service.request_magic_link(
                email="resetrate@authtest.example.com",
                ip_address="192.168.1.1",
                user_agent="TestBrowser/1.0",
            )

        assert mock_email_client.send_magic_link.call_count == config.rate_limit_attempts


class TestLogout:
    """Test logout (session revocation)."""

    def test_logout_revokes_session(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Logout revokes the session token."""
        cleanup_user("logout@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("logout@authtest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "logout@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        auth_result = auth_service.verify_magic_link(
            token=token,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )
        session_token = auth_result.session.token

        auth_service.logout(
            session_token=session_token,
            ip_address="192.168.1.1",
        )

        with pytest.raises(SessionExpiredError):
            auth_service.validate_session(session_token)

    def test_logout_nonexistent_session_does_not_error(
        self, auth_service, cleanup_security_events
    ):
        """Logout with invalid session doesn't raise."""
        auth_service.logout(
            session_token="nonexistent-session-token",
            ip_address="192.168.1.1",
        )

    def test_logout_logs_security_event(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Logout creates security event."""
        cleanup_user("logoutevent@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("logoutevent@authtest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "logoutevent@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        auth_result = auth_service.verify_magic_link(
            token=token,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        auth_service.logout(
            session_token=auth_result.session.token,
            ip_address="10.0.0.99",
        )

        event = db_admin.execute_single(
            """SELECT event_type, ip_address
               FROM security_events
               WHERE user_id = %s AND event_type = 'session_revoked'""",
            (str(user_id),),
        )
        assert event is not None
        assert str(event["ip_address"]) == "10.0.0.99"


class TestValidateSession:
    """Test session validation delegation."""

    def test_valid_session_returns_session(
        self, db_admin, auth_service, cleanup_user, cleanup_security_events
    ):
        """Valid session token returns Session object."""
        cleanup_user("validsess@authtest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("validsess@authtest.example.com",),
        )
        user_id = result[0]["id"]
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, str(user_id), "validsess@authtest.example.com", now, now + timedelta(minutes=10)),
        )

        auth_result = auth_service.verify_magic_link(
            token=token,
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        session = auth_service.validate_session(auth_result.session.token)

        assert session is not None
        assert session.user_id == user_id

    def test_invalid_session_raises(self, auth_service):
        """Invalid session token raises SessionExpiredError."""
        with pytest.raises(SessionExpiredError):
            auth_service.validate_session("invalid-session-token")
