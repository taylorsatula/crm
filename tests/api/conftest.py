"""API fixtures for the private workspace-authenticated service."""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.actions import create_actions_router
from api.data import create_data_router
from api.errors import register_error_handlers
from api.middleware import InternalWorkspaceMiddleware, RequestIDMiddleware
from api.workspace import create_workspace_router

INTERNAL_SECRET = "test-internal-service-secret"


@pytest.fixture
def app(services, db):
    app = FastAPI()
    app.include_router(create_data_router(services), prefix="/api")
    app.include_router(create_actions_router(services), prefix="/api")
    app.include_router(create_workspace_router(db), prefix="/api")
    app.add_middleware(InternalWorkspaceMiddleware, internal_service_secret=INTERNAL_SECRET)
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    return app


@pytest.fixture
def client(app, test_workspace_id):
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={
            "Authorization": f"Bearer {INTERNAL_SECRET}",
            "X-Workspace-ID": str(test_workspace_id),
            "X-Workspace-Timezone": "America/Chicago",
        },
    )


@pytest.fixture
def unauthed_client(app):
    return TestClient(app, raise_server_exceptions=False)
