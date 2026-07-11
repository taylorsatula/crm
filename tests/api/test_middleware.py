"""Tests for request IDs, workspace tokens, and lifecycle authentication."""

import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel
from starlette.testclient import TestClient

from api.base import success_response
from api.errors import register_error_handlers
from api.middleware import RequestIDMiddleware, WorkspaceAccessMiddleware
from utils.workspace_context import get_current_workspace_id, get_current_workspace_timezone

LIFECYCLE_SECRET = "lifecycle-secret"
WORKSPACE_TOKEN = "crm_ws_middleware_test"


class BodyPayload(BaseModel):
    name: str


class FakePostgres:
    def __init__(self, workspace_id: UUID, scopes: list[str] | None = None):
        self.workspace_id = workspace_id
        self.scopes = scopes or ["read", "write"]
        self.token_id = uuid4()
        self.last_used_updates = 0

    def execute_single(self, query, params=None):
        if "FROM workspace_access_tokens" in query:
            expected = hashlib.sha256(WORKSPACE_TOKEN.encode()).hexdigest()
            if params[0] != expected:
                return None
            return {
                "id": self.token_id,
                "workspace_id": self.workspace_id,
                "scopes": self.scopes,
            }
        if "SELECT timezone FROM workspaces" in query:
            return {"timezone": "America/Chicago"}
        raise AssertionError(query)

    def execute(self, query, params=None):
        if "UPDATE workspace_access_tokens" not in query:
            raise AssertionError(query)
        self.last_used_updates += 1
        return []


@pytest.fixture
def app():
    workspace_id = uuid4()
    postgres = FakePostgres(workspace_id)
    app = FastAPI()
    app.state.fake_postgres = postgres
    app.state.workspace_id = workspace_id

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
        return success_response(
            {"name": body.name},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @app.get("/api/lifecycle/ping")
    async def lifecycle_ping(request: Request):
        return success_response(
            {"authenticated": request.state.lifecycle_authenticated},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    app.add_middleware(
        WorkspaceAccessMiddleware,
        postgres=postgres,
        lifecycle_service_secret=LIFECYCLE_SECRET,
    )
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    return app


def _token_headers(**overrides: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {WORKSPACE_TOKEN}"}
    headers.update(overrides)
    return headers


def test_health_bypasses_authentication(app):
    assert TestClient(app).get("/health/live").status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_invalid_workspace_token_is_rejected(app, headers):
    response = TestClient(app).get("/api/context", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
    assert UUID(response.headers["X-Request-ID"])


def test_valid_token_sets_workspace_context_from_database(app):
    response = TestClient(app).get("/api/context", headers=_token_headers())
    assert response.status_code == 200
    assert response.json()["data"] == {
        "workspace_id": str(app.state.workspace_id),
        "timezone": "America/Chicago",
        "state_workspace_id": str(app.state.workspace_id),
    }
    assert app.state.fake_postgres.last_used_updates == 1


@pytest.mark.parametrize("header", ["X-Workspace-ID", "X-Workspace-Timezone"])
def test_client_workspace_identity_headers_are_rejected(app, header):
    response = TestClient(app).get(
        "/api/context",
        headers=_token_headers(**{header: "spoofed"}),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_token_scope_is_enforced(app):
    app.state.fake_postgres.scopes = ["read"]
    response = TestClient(app).post(
        "/api/echo",
        headers=_token_headers(),
        json={"name": "Ada"},
    )
    assert response.status_code == 403


def test_lifecycle_path_requires_separate_secret(app):
    workspace_response = TestClient(app).get(
        "/api/lifecycle/ping",
        headers=_token_headers(),
    )
    lifecycle_response = TestClient(app).get(
        "/api/lifecycle/ping",
        headers={"Authorization": f"Bearer {LIFECYCLE_SECRET}"},
    )
    assert workspace_response.status_code == 401
    assert lifecycle_response.status_code == 200
    assert lifecycle_response.json()["data"]["authenticated"] is True


def test_browser_cookie_cannot_authenticate_request(app):
    response = TestClient(app, cookies={"session_token": "legacy-browser-session"}).get(
        "/api/context"
    )
    assert response.status_code == 401


def test_request_id_matches_success_and_validation_response(app):
    client = TestClient(app)
    success = client.post("/api/echo", headers=_token_headers(), json={"name": "Ada"})
    invalid = client.post("/api/echo", headers=_token_headers(), json={})
    assert success.json()["meta"]["request_id"] == success.headers["X-Request-ID"]
    assert invalid.json()["meta"]["request_id"] == invalid.headers["X-Request-ID"]
