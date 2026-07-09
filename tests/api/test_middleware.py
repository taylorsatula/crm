"""Tests for request IDs and the internal workspace boundary."""

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.testclient import TestClient

from api.base import success_response
from api.errors import register_error_handlers
from api.middleware import InternalWorkspaceMiddleware, RequestIDMiddleware
from utils.workspace_context import get_current_workspace_id, get_current_workspace_timezone

SECRET = "internal-secret"


class BodyPayload(BaseModel):
    name: str


@pytest.fixture
def app():
    app = FastAPI()

    @app.get("/health/live")
    async def health():
        return {"ok": True}

    @app.get("/api/context")
    async def context(request: Request):
        return success_response(
            {
                "workspace_id": str(get_current_workspace_id()),
                "timezone": get_current_workspace_timezone(),
                "state_workspace_id": str(request.state.workspace_id),
            },
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @app.post("/api/echo")
    async def echo(request: Request, body: BodyPayload):
        return success_response({"name": body.name}, request_id=request.state.request_id).model_dump(mode="json")

    app.add_middleware(InternalWorkspaceMiddleware, internal_service_secret=SECRET)
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    return app


def _headers(workspace_id: UUID | None = None, **overrides: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {SECRET}",
        "X-Workspace-ID": str(workspace_id or uuid4()),
        "X-Workspace-Timezone": "America/Chicago",
    }
    headers.update(overrides)
    return headers


def test_health_bypasses_internal_auth(app):
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong", "X-Workspace-ID": str(uuid4()), "X-Workspace-Timezone": "UTC"},
        {"Authorization": f"Bearer {SECRET}", "X-Workspace-ID": "not-a-uuid", "X-Workspace-Timezone": "UTC"},
        {"Authorization": f"Bearer {SECRET}", "X-Workspace-ID": str(uuid4()), "X-Workspace-Timezone": "not/a-timezone"},
    ],
)
def test_invalid_internal_request_is_rejected_before_route(app, headers):
    response = TestClient(app).get("/api/context", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert UUID(response.headers["X-Request-ID"])


def test_valid_internal_request_sets_workspace_context_and_request_state(app):
    workspace_id = uuid4()
    response = TestClient(app).get("/api/context", headers=_headers(workspace_id))
    assert response.status_code == 200
    assert response.json()["data"] == {
        "workspace_id": str(workspace_id),
        "timezone": "America/Chicago",
        "state_workspace_id": str(workspace_id),
    }


def test_browser_cookie_cannot_authenticate_request(app):
    response = TestClient(app, cookies={"session_token": "legacy-browser-session"}).get("/api/context")
    assert response.status_code == 401


def test_request_id_matches_success_and_validation_response(app):
    client = TestClient(app)
    success = client.post("/api/echo", headers=_headers(), json={"name": "Ada"})
    invalid = client.post("/api/echo", headers=_headers(), json={})
    assert success.json()["meta"]["request_id"] == success.headers["X-Request-ID"]
    assert invalid.json()["meta"]["request_id"] == invalid.headers["X-Request-ID"]
