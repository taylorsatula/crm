"""Tests for RequestIDMiddleware."""

import pytest
from uuid import UUID
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.testclient import TestClient

from api.base import success_response
from api.errors import register_error_handlers
from api.middleware import RequestIDMiddleware
from auth.security_middleware import AuthMiddleware


@pytest.fixture
def app():
    """Minimal FastAPI app with RequestIDMiddleware."""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/test")
    async def test_endpoint(request: Request):
        return JSONResponse({"request_id": request.state.request_id})

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestRequestIDMiddleware:
    """Tests for RequestIDMiddleware."""

    def test_response_has_request_id_header(self, client):
        """Response includes X-Request-ID header."""
        response = client.get("/test")

        assert "X-Request-ID" in response.headers
        # Should be a valid UUID
        UUID(response.headers["X-Request-ID"])

    def test_request_state_has_request_id(self, client):
        """request.state.request_id is set and matches header."""
        response = client.get("/test")

        header_id = response.headers["X-Request-ID"]
        body_id = response.json()["request_id"]
        assert header_id == body_id

    def test_each_request_gets_unique_id(self, client):
        """Different requests get different IDs."""
        r1 = client.get("/test")
        r2 = client.get("/test")

        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]


class BodyPayload(BaseModel):
    name: str


class RejectingSessionManager:
    def validate_session(self, token: str):
        raise AssertionError("session validation should not run without a cookie")


@pytest.fixture
def app_with_errors_and_auth():
    """App that mirrors production middleware order for request ID propagation."""
    app = FastAPI()

    @app.post("/health/echo")
    async def echo(request: Request, body: BodyPayload):
        return success_response(
            {"name": body.name},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @app.get("/api/protected")
    async def protected():
        return {"ok": True}

    app.add_middleware(AuthMiddleware, session_manager=RejectingSessionManager())
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    return app


class TestRequestIDPropagation:
    """Request ID is the same in headers and response bodies."""

    def test_auth_401_includes_header_and_body_request_id(self, app_with_errors_and_auth):
        response = TestClient(app_with_errors_and_auth).get("/api/protected")

        assert response.status_code == 401
        assert UUID(response.headers["X-Request-ID"])
        assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]

    def test_validation_error_body_request_id_matches_header(self, app_with_errors_and_auth):
        response = TestClient(app_with_errors_and_auth).post(
            "/health/echo",
            json={},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]

    def test_success_body_request_id_matches_header(self, app_with_errors_and_auth):
        response = TestClient(app_with_errors_and_auth).post(
            "/health/echo",
            json={"name": "Ada"},
        )

        assert response.status_code == 200
        assert response.json()["data"] == {"name": "Ada"}
        assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]
