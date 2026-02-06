"""Tests for RequestIDMiddleware."""

import pytest
from uuid import UUID
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from api.middleware import RequestIDMiddleware


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
