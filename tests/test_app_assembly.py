"""Tests for FastAPI application assembly."""

from pathlib import Path

from starlette.testclient import TestClient

from core.event_bus import EventBus
from main import create_app, wire_event_handlers


class FakeService:
    pass


class FakeSessionManager:
    def validate_session(self, token: str):
        raise AssertionError("no authenticated routes are exercised in this test")


class FakeContainer:
    def __init__(self):
        self.closed = False
        self.session_manager = FakeSessionManager()
        self.event_bus = EventBus()
        self.health_checks = {
            "database": FakeService(),
            "cache": FakeService(),
            "vault": FakeService(),
            "llm": FakeService(),
            "email": FakeService(),
        }
        self.services = {
            "customer": FakeService(),
            "ticket": FakeService(),
            "catalog": FakeService(),
            "line_item": FakeService(),
            "invoice": FakeService(),
            "note": FakeService(),
            "attribute": FakeService(),
            "message": FakeService(),
            "address": FakeService(),
        }
        self.auth_service = FakeService()
        self.auth_components = {"session_manager": self.session_manager}
        self.clients = {}
        self.event_handlers = {}

    def close(self):
        self.closed = True


class RecordingFactory:
    def __init__(self):
        self.calls = 0
        self.container = FakeContainer()

    def __call__(self):
        self.calls += 1
        return self.container


def test_create_app_registers_phase_5_routes():
    app = create_app(container_factory=RecordingFactory())
    route_paths = {route.path for route in app.routes}

    assert {
        "/",
        "/health",
        "/health/ready",
        "/health/live",
        "/api/data",
        "/api/actions",
        "/auth/request-link",
        "/auth/me",
    }.issubset(route_paths)


def test_lifespan_factory_sets_app_state_and_closes_container():
    factory = RecordingFactory()
    app = create_app(container_factory=factory)

    with TestClient(app):
        assert factory.calls == 1
        assert app.state.container is factory.container
        assert app.state.services is factory.container.services
        assert app.state.auth_service is factory.container.auth_service
        assert factory.container.closed is False

    assert factory.container.closed is True


def test_event_bus_subscriptions_are_wired():
    event_bus = EventBus()
    services = {
        "attribute": FakeService(),
        "note": FakeService(),
        "message": FakeService(),
    }
    handlers = wire_event_handlers(event_bus, FakeService(), services)

    assert set(handlers) == {"TicketCompleted", "TicketCancelled", "InvoicePaid"}
    assert {name: len(callbacks) for name, callbacks in event_bus._subscribers.items()} == {
        "TicketCompleted": 1,
        "TicketCancelled": 1,
        "InvoicePaid": 1,
    }


def test_assets_are_public_and_served_from_static():
    factory = RecordingFactory()
    app = create_app(container_factory=factory)
    static_file = Path(__file__).resolve().parents[1] / "static" / "health.txt"

    assert static_file.read_text().strip() == "assets-ok"
    response = TestClient(app).get("/assets/health.txt")

    assert response.status_code == 200
    assert response.text.strip() == "assets-ok"


def test_root_app_shell_is_public_html():
    factory = RecordingFactory()
    app = create_app(container_factory=factory)

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<script type="module" src="/assets/js/app.js"></script>' in response.text


def test_protected_api_stays_protected_without_session():
    factory = RecordingFactory()
    app = create_app(container_factory=factory)

    response = TestClient(app).get("/api/data", params={"type": "customers"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
