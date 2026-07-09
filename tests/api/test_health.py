"""Tests for private-infrastructure health endpoints."""

from fastapi import FastAPI
from starlette.testclient import TestClient

from api.health import create_health_router
from api.middleware import RequestIDMiddleware


class RecordingHealthCheck:
    def __init__(self, *, healthy: bool = True, failure: Exception | None = None):
        self.healthy = healthy
        self.failure = failure
        self.calls = 0

    def health_check(self) -> bool:
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.healthy


def _health_checks(**overrides):
    checks = {name: RecordingHealthCheck() for name in ("database", "vault", "llm", "email")}
    checks.update(overrides)
    return checks


def _client_for(checks):
    app = FastAPI()
    app.include_router(create_health_router(checks))
    app.add_middleware(RequestIDMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_health_returns_all_dependency_statuses_when_healthy():
    checks = _health_checks()
    response = _client_for(checks).get("/health")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "healthy"
    assert set(response.json()["data"]["checks"]) == {"database", "vault", "llm", "email"}


def test_health_returns_503_with_diagnostics_when_dependency_fails():
    response = _client_for(_health_checks(email=RecordingHealthCheck(failure=RuntimeError("gateway down")))).get("/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["data"]["checks"]["email"] == {"status": "unhealthy", "message": "gateway down"}


def test_live_does_not_run_dependency_checks():
    checks = _health_checks(database=RecordingHealthCheck(failure=RuntimeError("db unavailable")))
    response = _client_for(checks).get("/health/live")
    assert response.status_code == 200
    assert all(check.calls == 0 for check in checks.values())
