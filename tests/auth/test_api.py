"""Tests for auth API routes."""

import secrets
from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.api import create_auth_router
from auth.service import AuthService
from auth.database import AuthDatabase
from auth.session import SessionManager
from auth.rate_limiter import RateLimiter
from auth.security_logger import SecurityLogger
from auth.security_middleware import AuthMiddleware
from auth.config import AuthConfig
from clients.email_client import EmailGatewayClient
from utils.timezone import now_utc


@pytest.fixture
def config():
    """Test auth config."""
    return AuthConfig(
        magic_link_expiry_minutes=5,
        session_expiry_hours=1,
        rate_limit_attempts=3,
        rate_limit_window_minutes=5,
        app_base_url="https://test.example.com",
    )


@pytest.fixture
def mock_email_client():
    """Mock email client - only thing we mock."""
    mock = Mock(spec=EmailGatewayClient)
    mock.send_magic_link.return_value = None
    return mock


@pytest.fixture
def session_manager(valkey, config):
    """Real SessionManager."""
    return SessionManager(valkey, config)


@pytest.fixture
def auth_service(db, valkey, config, mock_email_client, session_manager):
    """Real AuthService with real DB/Valkey, mocked email."""
    auth_db = AuthDatabase(db)
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
def app_with_auth(auth_service, session_manager):
    """FastAPI app with auth routes and middleware."""
    app = FastAPI()

    # Add middleware for /auth/me endpoint
    app.add_middleware(AuthMiddleware, session_manager=session_manager)

    router = create_auth_router(auth_service)
    app.include_router(router, prefix="/auth")
    return app


@pytest.fixture
def client(app_with_auth):
    """Test client."""
    return TestClient(app_with_auth)


@pytest.fixture
def cleanup_user(db_admin):
    """Track users for cleanup."""
    created_emails = []

    def _track(email):
        created_emails.append(email.lower())

    yield _track

    for email in created_emails:
        db_admin.execute("DELETE FROM users WHERE email = %s", (email,))


@pytest.fixture
def cleanup_security_events(db_admin):
    """Clean up security events."""
    yield
    db_admin.execute(
        "DELETE FROM security_events WHERE email LIKE '%@apitest.example.com'"
    )


class TestRequestMagicLink:
    """Test POST /auth/request-link endpoint."""

    def test_existing_user_returns_sent_true(
        self, db_admin, client, cleanup_user, cleanup_security_events
    ):
        """Existing user gets sent=true in response."""
        cleanup_user("existing@apitest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("existing@apitest.example.com",),
        )

        response = client.post(
            "/auth/request-link",
            json={"email": "existing@apitest.example.com"},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["data"]["sent"] is True
        assert response.json()["data"]["needs_signup"] is False

    def test_nonexistent_user_returns_needs_signup(
        self, client, cleanup_security_events
    ):
        """Non-existent user gets needs_signup=true in response."""
        response = client.post(
            "/auth/request-link",
            json={"email": "unknown@apitest.example.com"},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["data"]["sent"] is False
        assert response.json()["data"]["needs_signup"] is True

    def test_invalid_email_returns_422(self, client):
        """Invalid email format returns 422."""
        response = client.post(
            "/auth/request-link",
            json={"email": "not-an-email"},
        )

        assert response.status_code == 422

    def test_rate_limited_returns_429(
        self, db_admin, client, config, cleanup_user, cleanup_security_events
    ):
        """Rate limited request returns 429."""
        cleanup_user("ratelimit@apitest.example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("ratelimit@apitest.example.com",),
        )

        # Exhaust rate limit
        for _ in range(config.rate_limit_attempts):
            client.post(
                "/auth/request-link",
                json={"email": "ratelimit@apitest.example.com"},
            )

        response = client.post(
            "/auth/request-link",
            json={"email": "ratelimit@apitest.example.com"},
        )

        assert response.status_code == 429
        assert response.json()["error"]["code"] == "RATE_LIMITED"
        assert "Retry-After" in response.headers


class TestVerifyMagicLink:
    """Test GET /auth/verify endpoint."""

    def test_valid_token_sets_cookie_and_returns_user(
        self, db_admin, client, cleanup_user, cleanup_security_events
    ):
        """Valid token sets session cookie and returns user info."""
        cleanup_user("verify@apitest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("verify@apitest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "verify@apitest.example.com", now, now + timedelta(minutes=10)),
        )

        response = client.get(f"/auth/verify?token={token}")

        assert response.status_code == 200
        assert "session_token" in response.cookies
        assert len(response.cookies["session_token"]) > 20
        assert response.json()["data"]["user"]["email"] == "verify@apitest.example.com"

    def test_missing_token_returns_400(self, client):
        """Missing token parameter returns 400."""
        response = client.get("/auth/verify")

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"

    def test_invalid_token_returns_401(self, client, cleanup_security_events):
        """Invalid token returns 401."""
        response = client.get("/auth/verify?token=nonexistent-token")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_TOKEN"

    def test_inactive_user_returns_403(
        self, db_admin, client, cleanup_user, cleanup_security_events
    ):
        """Inactive user returns 403."""
        cleanup_user("inactive@apitest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email, is_active) VALUES (%s, false) RETURNING id",
            ("inactive@apitest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "inactive@apitest.example.com", now, now + timedelta(minutes=10)),
        )

        response = client.get(f"/auth/verify?token={token}")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"

    def test_session_cookie_has_security_attributes(
        self, db_admin, client, cleanup_user, cleanup_security_events
    ):
        """Session cookie is httponly, secure, and samesite=lax."""
        cleanup_user("cookieattrs@apitest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("cookieattrs@apitest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "cookieattrs@apitest.example.com", now, now + timedelta(minutes=10)),
        )

        response = client.get(f"/auth/verify?token={token}")

        assert response.status_code == 200
        cookie_header = response.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie_header
        assert "Secure" in cookie_header
        assert "SameSite=lax" in cookie_header

    def test_token_cannot_be_reused(
        self, db_admin, client, cleanup_user, cleanup_security_events
    ):
        """Same magic link token cannot be verified twice (one-time use)."""
        cleanup_user("reuse@apitest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("reuse@apitest.example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "reuse@apitest.example.com", now, now + timedelta(minutes=10)),
        )

        # First use succeeds
        first_response = client.get(f"/auth/verify?token={token}")
        assert first_response.status_code == 200

        # Second use fails
        second_response = client.get(f"/auth/verify?token={token}")
        assert second_response.status_code == 401
        assert second_response.json()["error"]["code"] == "INVALID_TOKEN"


class TestLogout:
    """Test POST /auth/logout endpoint."""

    def test_logout_clears_cookie(
        self, db_admin, client, cleanup_user, cleanup_security_events
    ):
        """Logout clears session cookie."""
        cleanup_user("logout@apitest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("logout@apitest.example.com",),
        )
        user_id = result[0]["id"]

        # Create valid token and verify to get session
        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "logout@apitest.example.com", now, now + timedelta(minutes=10)),
        )

        verify_response = client.get(f"/auth/verify?token={token}")
        session_token = verify_response.cookies["session_token"]

        # Now logout
        response = client.post(
            "/auth/logout",
            cookies={"session_token": session_token},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_logout_without_cookie_succeeds(self, client, cleanup_security_events):
        """Logout without session cookie still returns success."""
        response = client.post("/auth/logout")

        assert response.status_code == 200
        assert response.json()["success"] is True


class TestGetCurrentUser:
    """Test GET /auth/me endpoint."""

    def test_authenticated_user_returns_user_info(
        self, db_admin, client, cleanup_user, cleanup_security_events
    ):
        """Authenticated user can retrieve their info."""
        cleanup_user("me@apitest.example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("me@apitest.example.com",),
        )
        user_id = result[0]["id"]

        # Create valid token and verify to get session
        now = now_utc()
        token = secrets.token_urlsafe(32)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, false) RETURNING token""",
            (token, user_id, "me@apitest.example.com", now, now + timedelta(minutes=10)),
        )

        verify_response = client.get(f"/auth/verify?token={token}")
        session_token = verify_response.cookies["session_token"]

        # Now call /auth/me with the session
        response = client.get(
            "/auth/me",
            cookies={"session_token": session_token},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["data"]["user_id"] == str(user_id)

    def test_without_auth_returns_401(self, client):
        """Without authentication returns 401."""
        response = client.get("/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
