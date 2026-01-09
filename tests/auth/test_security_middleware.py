"""Tests for AuthMiddleware - session validation and user context."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auth.security_middleware import AuthMiddleware
from auth.session import SessionManager
from auth.types import Session
from auth.exceptions import SessionExpiredError
from utils.timezone import now_utc


@pytest.fixture
def mock_session_manager():
    """Mock SessionManager."""
    return Mock(spec=SessionManager)


@pytest.fixture
def app_with_middleware(mock_session_manager):
    """FastAPI app with auth middleware."""
    app = FastAPI()

    app.add_middleware(
        AuthMiddleware,
        session_manager=mock_session_manager,
    )

    @app.get("/api/data/protected")
    async def protected_route(request: Request):
        return {"user_id": str(request.state.user_id)}

    @app.get("/auth/request-link")
    async def public_request_link():
        return {"public": True}

    @app.get("/auth/verify")
    async def public_verify():
        return {"public": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/docs")
    async def docs():
        return {"docs": True}

    @app.get("/openapi.json")
    async def openapi():
        return {"openapi": "3.0"}

    @app.get("/assets/{path:path}")
    async def asset_files(path: str):
        return {"asset": path}

    return app


class TestPublicPaths:
    """Test that public paths skip authentication."""

    def test_auth_request_link_no_cookie_succeeds(self, app_with_middleware):
        """Auth request-link endpoint works without session cookie."""
        client = TestClient(app_with_middleware)

        response = client.get("/auth/request-link")

        assert response.status_code == 200
        assert response.json()["public"] is True

    def test_auth_verify_no_cookie_succeeds(self, app_with_middleware):
        """Auth verify endpoint works without session cookie."""
        client = TestClient(app_with_middleware)

        response = client.get("/auth/verify")

        assert response.status_code == 200
        assert response.json()["public"] is True

    def test_health_endpoint_no_cookie_succeeds(self, app_with_middleware):
        """Health endpoint works without auth."""
        client = TestClient(app_with_middleware)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_docs_endpoint_no_cookie_succeeds(self, app_with_middleware):
        """Docs endpoint works without auth."""
        client = TestClient(app_with_middleware)

        response = client.get("/docs")

        assert response.status_code == 200

    def test_openapi_endpoint_no_cookie_succeeds(self, app_with_middleware):
        """OpenAPI endpoint works without auth."""
        client = TestClient(app_with_middleware)

        response = client.get("/openapi.json")

        assert response.status_code == 200

    def test_assets_path_no_cookie_succeeds(self, app_with_middleware):
        """Asset paths work without auth."""
        client = TestClient(app_with_middleware)

        response = client.get("/assets/style.css")

        assert response.status_code == 200
        assert response.json()["asset"] == "style.css"

    def test_public_path_with_invalid_cookie_still_succeeds(
        self, app_with_middleware, mock_session_manager
    ):
        """Public paths ignore invalid session cookies."""
        mock_session_manager.validate_session.side_effect = SessionExpiredError("expired")
        client = TestClient(app_with_middleware)

        response = client.get("/health", cookies={"session_token": "invalid-token"})

        assert response.status_code == 200

    def test_public_path_with_query_params_matches(self, app_with_middleware):
        """Public path with query params still matches."""
        client = TestClient(app_with_middleware)

        response = client.get("/auth/verify?token=abc123")

        assert response.status_code == 200
        assert response.json()["public"] is True


class TestProtectedPaths:
    """Test protected path authentication."""

    def test_no_cookie_returns_401(self, app_with_middleware):
        """Protected path without cookie returns 401."""
        client = TestClient(app_with_middleware)

        response = client.get("/api/data/protected")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"

    def test_invalid_session_returns_401(self, app_with_middleware, mock_session_manager):
        """Invalid session cookie returns 401."""
        mock_session_manager.validate_session.side_effect = SessionExpiredError("expired")
        client = TestClient(app_with_middleware)

        response = client.get("/api/data/protected", cookies={"session_token": "invalid-token"})

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SESSION_EXPIRED"

    def test_valid_session_sets_user_in_request_state(
        self, app_with_middleware, mock_session_manager, test_user_id
    ):
        """Valid session sets user_id in request state."""
        now = now_utc()

        mock_session_manager.validate_session.return_value = Session(
            token="valid-token",
            user_id=test_user_id,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
        )

        client = TestClient(app_with_middleware)

        response = client.get("/api/data/protected", cookies={"session_token": "valid-token"})

        assert response.status_code == 200
        assert response.json()["user_id"] == str(test_user_id)

    def test_session_manager_called_with_token(
        self, app_with_middleware, mock_session_manager, test_user_id
    ):
        """Session manager is called with the cookie token."""
        now = now_utc()
        mock_session_manager.validate_session.return_value = Session(
            token="the-token-value",
            user_id=test_user_id,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
        )

        client = TestClient(app_with_middleware)

        client.get("/api/data/protected", cookies={"session_token": "the-token-value"})

        mock_session_manager.validate_session.assert_called_once_with("the-token-value")


class TestUserContext:
    """Test user context lifecycle."""

    def test_different_users_get_correct_context(
        self, app_with_middleware, mock_session_manager, test_user_id, test_user_b_id
    ):
        """Different sessions return correct user IDs."""
        now = now_utc()

        client = TestClient(app_with_middleware)

        # First request as user A
        mock_session_manager.validate_session.return_value = Session(
            token="token-a",
            user_id=test_user_id,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
        )
        response_a = client.get("/api/data/protected", cookies={"session_token": "token-a"})

        # Second request as user B
        mock_session_manager.validate_session.return_value = Session(
            token="token-b",
            user_id=test_user_b_id,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
        )
        response_b = client.get("/api/data/protected", cookies={"session_token": "token-b"})

        assert response_a.json()["user_id"] == str(test_user_id)
        assert response_b.json()["user_id"] == str(test_user_b_id)


class TestCookieName:
    """Test session cookie configuration."""

    def test_reads_from_session_token_cookie(
        self, app_with_middleware, mock_session_manager, test_user_id
    ):
        """Reads token from 'session_token' cookie specifically."""
        now = now_utc()
        mock_session_manager.validate_session.return_value = Session(
            token="correct-token",
            user_id=test_user_id,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
        )

        client = TestClient(app_with_middleware)

        # Wrong cookie name should fail
        response_wrong = client.get("/api/data/protected", cookies={"session": "wrong-cookie-name"})
        assert response_wrong.status_code == 401

        # Correct cookie name should work
        response_right = client.get("/api/data/protected", cookies={"session_token": "correct-token"})
        assert response_right.status_code == 200
