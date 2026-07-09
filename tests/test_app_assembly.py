"""Tests for private CRM service assembly."""

from uuid import uuid4

from starlette.testclient import TestClient

from config import AppConfig
from core.event_bus import EventBus
from main import create_app, wire_event_handlers


class FakeService:
    def health_check(self):
        return True


class FakeDatabase(FakeService):
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    def execute(self, query, params=None):
        return []


class FakeContainer:
    def __init__(self):
        self.database = FakeDatabase()
        self.event_bus = EventBus()
        self.services = {name: FakeService() for name in (
            "customer", "ticket", "catalog", "line_item", "invoice", "note",
            "attribute", "message", "address",
        )}
        self.clients = {
            "database": self.database,
            "vault": FakeService(),
            "llm": FakeService(),
            "email": FakeService(),
        }
        self.health_checks = self.clients
        self.event_handlers = {}
        self.internal_service_secret = "assembly-secret"
        self.closed = False

    def close(self):
        self.closed = True
        self.database.close()


class RecordingFactory:
    def __init__(self):
        self.calls = 0
        self.container = FakeContainer()

    def __call__(self):
        self.calls += 1
        return self.container


def _headers():
    return {
        "Authorization": "Bearer assembly-secret",
        "X-Workspace-ID": str(uuid4()),
        "X-Workspace-Timezone": "UTC",
    }


def test_private_service_registers_only_domain_workspace_and_health_routes():
    app = create_app(container_factory=RecordingFactory())
    route_paths = {route.path for route in app.routes}
    assert {"/health", "/health/ready", "/health/live", "/api/data", "/api/actions", "/api/workspace/provision", "/api/workspace"}.issubset(route_paths)
    assert "/" not in route_paths
    assert all(not path.startswith("/auth") for path in route_paths)
    assert "/docs" not in route_paths


def test_lifespan_sets_state_and_closes_container():
    factory = RecordingFactory()
    with TestClient(create_app(container_factory=factory)) as client:
        assert factory.calls == 1
        assert client.app.state.container is factory.container
        assert client.app.state.services is factory.container.services
        assert factory.container.closed is False
    assert factory.container.closed is True
    assert factory.container.database.closed is True


def test_legacy_public_routes_are_absent_when_authenticated():
    app = create_app(container_factory=RecordingFactory())
    with TestClient(app) as client:
        for path in ("/", "/auth/me", "/assets/js/app.js", "/docs", "/openapi.json"):
            assert client.get(path, headers=_headers()).status_code == 404


def test_event_bus_subscriptions_are_wired():
    event_bus = EventBus()
    handlers = wire_event_handlers(event_bus, FakeService(), {"attribute": FakeService(), "note": FakeService(), "message": FakeService()})
    assert set(handlers) == {"TicketCompleted", "TicketCancelled", "InvoicePaid"}


def test_docs_can_only_be_enabled_explicitly_for_private_development():
    app = create_app(container_factory=RecordingFactory(), config=AppConfig(expose_docs=True))
    assert "/docs" in {route.path for route in app.routes}
