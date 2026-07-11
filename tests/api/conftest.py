"""API fixtures for the private workspace-authenticated service."""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.actions import create_actions_router
from api.data import create_data_router
from api.errors import register_error_handlers
from api.middleware import RequestIDMiddleware, WorkspaceAccessMiddleware
from api.workspace import create_workspace_router
from tests.conftest import TEST_WORKSPACE_TOKEN

LIFECYCLE_SECRET = "test-lifecycle-service-secret"


@pytest.fixture
def app(services, db):
    app = FastAPI()
    app.include_router(create_data_router(services), prefix="/api")
    app.include_router(create_actions_router(services), prefix="/api")
    app.include_router(create_workspace_router(db), prefix="/api")
    app.add_middleware(
        WorkspaceAccessMiddleware,
        postgres=db,
        lifecycle_service_secret=LIFECYCLE_SECRET,
    )
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    return app


@pytest.fixture
def client(app, test_workspace_id):
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={
            "Authorization": f"Bearer {TEST_WORKSPACE_TOKEN}",
        },
    )


@pytest.fixture
def unauthed_client(app):
    return TestClient(app, raise_server_exceptions=False)
