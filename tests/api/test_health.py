"""Tests for process and dependency health endpoints."""

from fastapi import FastAPI
from starlette.testclient import TestClient

from api.health import create_health_router
from api.middleware import RequestIDMiddleware
from auth.security_middleware import AuthMiddleware


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


class RejectingSessionManager:
    def validate_session(self, token: str):
        raise AssertionError("health endpoints must not require a session")


def _health_checks(**overrides):
    checks = {
        "database": RecordingHealthCheck(),
        "cache": RecordingHealthCheck(),
        "vault": RecordingHealthCheck(),
        "llm": RecordingHealthCheck(),
        "email": RecordingHealthCheck(),
    }
    checks.update(overrides)
    return checks


def _client_for(checks: dict[str, RecordingHealthCheck]) -> TestClient:
    app = FastAPI()
    app.include_router(create_health_router(checks))
    app.add_middleware(AuthMiddleware, session_manager=RejectingSessionManager())
    app.add_middleware(RequestIDMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_health_returns_all_dependency_statuses_when_healthy():
    checks = _health_checks()
    response = _client_for(checks).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "healthy"
    assert set(body["data"]["checks"]) == {"database", "cache", "vault", "llm", "email"}
    assert {
        service: check["status"]
        for service, check in body["data"]["checks"].items()
    } == {
        "database": "healthy",
        "cache": "healthy",
        "vault": "healthy",
        "llm": "healthy",
        "email": "healthy",
    }
    assert {name: check.calls for name, check in checks.items()} == {
        "database": 1,
        "cache": 1,
        "vault": 1,
        "llm": 1,
        "email": 1,
    }


def test_ready_uses_runtime_dependency_checks():
    checks = _health_checks()
    response = _client_for(checks).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "healthy"
    assert {name: check.calls for name, check in checks.items()} == {
        "database": 1,
        "cache": 1,
        "vault": 1,
        "llm": 1,
        "email": 1,
    }


def test_health_returns_503_with_diagnostics_when_dependency_fails():
    checks = _health_checks(email=RecordingHealthCheck(failure=RuntimeError("gateway down")))
    response = _client_for(checks).get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["data"]["status"] == "unhealthy"
    assert body["data"]["checks"]["email"]["status"] == "unhealthy"
    assert body["data"]["checks"]["email"]["message"] == "gateway down"
    assert body["data"]["checks"]["database"]["status"] == "healthy"


def test_live_returns_process_liveness_without_dependency_checks():
    checks = _health_checks(database=RecordingHealthCheck(failure=RuntimeError("db unavailable")))
    response = _client_for(checks).get("/health/live")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "alive"}
    assert {name: check.calls for name, check in checks.items()} == {
        "database": 0,
        "cache": 0,
        "vault": 0,
        "llm": 0,
        "email": 0,
    }


def test_health_endpoints_are_public_without_session_cookie():
    checks = _health_checks()
    client = _client_for(checks)

    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/health/live").status_code == 200
