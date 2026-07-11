"""FastAPI assembly for the private, workspace-scoped CRM service."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI

from api.actions import create_actions_router
from api.data import create_data_router
from api.errors import register_error_handlers
from api.health import create_health_router
from api.middleware import RequestIDMiddleware, WorkspaceAccessMiddleware
from api.workspace import create_workspace_router
from clients.email_client import EmailGatewayClient
from clients.llm_client import LLMClient
from clients.postgres_client import PostgresClient
from clients.vault_client import VaultClient
from config import AppConfig
from core.audit import AuditLogger
from core.event_bus import EventBus
from core.extraction import AttributeExtractor
from core.handlers.invoice_payment_handler import handle_invoice_paid
from core.handlers.ticket_cancellation_handler import handle_ticket_cancelled
from core.handlers.ticket_completion_handler import handle_ticket_completed
from core.services.address_service import AddressService
from core.services.attribute_service import AttributeService
from core.services.catalog_service import CatalogService
from core.services.customer_service import CustomerService
from core.services.invoice_service import InvoiceService
from core.services.line_item_service import LineItemService
from core.services.message_service import MessageService
from core.services.note_service import NoteService
from core.services.ticket_service import TicketService
from core.services.workspace_settings_service import WorkspaceSettingsService


@dataclass
class AppContainer:
    """Runtime dependencies assembled from Vault during application startup."""

    clients: dict[str, Any]
    services: dict[str, Any]
    event_bus: EventBus
    event_handlers: dict[str, Callable]
    health_checks: dict[str, Any]
    lifecycle_service_secret: str

    def close(self) -> None:
        """Close external connections owned by the app."""
        self.clients["database"].close()


class _ContainerRef:
    def __init__(self) -> None:
        self.container: AppContainer | None = None

    def get(self) -> AppContainer:
        if self.container is None:
            raise RuntimeError("Application container has not started")
        return self.container


class _ContainerProxy:
    def __init__(self, ref: _ContainerRef, resolver: Callable[[AppContainer], Any]):
        self._ref = ref
        self._resolver = resolver

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolver(self._ref.get()), name)


def _service_proxies(ref: _ContainerRef) -> dict[str, Any]:
    names = (
        "customer", "ticket", "catalog", "line_item", "invoice", "note",
        "attribute", "message", "address", "workspace_settings",
    )
    return {
        name: _ContainerProxy(ref, lambda container, key=name: container.services[key])
        for name in names
    }


def _health_proxies(ref: _ContainerRef) -> dict[str, Any]:
    return {
        name: _ContainerProxy(ref, lambda container, key=name: container.health_checks[key])
        for name in ("database", "vault", "llm", "email")
    }


def wire_event_handlers(
    event_bus: EventBus,
    extractor: AttributeExtractor,
    services: dict[str, Any],
) -> dict[str, Callable]:
    """Subscribe retained domain handlers to the in-process event bus."""
    handlers = {
        "TicketCompleted": handle_ticket_completed(extractor, services["attribute"], services["note"]),
        "TicketCancelled": handle_ticket_cancelled(services["message"]),
        "InvoicePaid": handle_invoice_paid(services["message"]),
    }
    for event_name, handler in handlers.items():
        event_bus.subscribe(event_name, handler)
    return handlers


def build_app_container() -> AppContainer:
    """Build the production container; required Vault data fails startup loudly."""
    load_dotenv(override=True)
    vault = VaultClient()
    lifecycle_service_secret = vault.get_secret("lifecycle", "service_secret")
    if not isinstance(lifecycle_service_secret, str) or not lifecycle_service_secret:
        raise ValueError("Vault secret crm/lifecycle.service_secret must be a non-empty string")

    postgres = PostgresClient(vault.get_secret("database", "url"))
    email_client = EmailGatewayClient(
        gateway_url=vault.get_secret("email", "gateway_url"),
        api_key=vault.get_secret("email", "api_key"),
        hmac_secret=vault.get_secret("email", "hmac_secret"),
        health_url=vault.get_secret("email", "health_url"),
    )
    llm = LLMClient(**vault.get_llm_config())
    audit = AuditLogger(postgres)
    event_bus = EventBus()
    services = {
        "customer": CustomerService(postgres, audit, event_bus),
        "ticket": TicketService(postgres, audit, event_bus),
        "catalog": CatalogService(postgres, audit),
        "line_item": LineItemService(postgres, audit),
        "invoice": InvoiceService(postgres, audit, event_bus),
        "note": NoteService(postgres, audit, event_bus),
        "attribute": AttributeService(postgres, audit),
        "message": MessageService(postgres, audit),
        "address": AddressService(postgres, audit),
        "workspace_settings": WorkspaceSettingsService(postgres),
    }
    event_handlers = wire_event_handlers(event_bus, AttributeExtractor(llm), services)
    clients = {"database": postgres, "vault": vault, "llm": llm, "email": email_client}
    return AppContainer(
        clients=clients,
        services=services,
        event_bus=event_bus,
        event_handlers=event_handlers,
        health_checks=clients,
        lifecycle_service_secret=lifecycle_service_secret,
    )


def create_app(
    *,
    container_factory: Callable[[], AppContainer] = build_app_container,
    config: AppConfig | None = None,
) -> FastAPI:
    """Create the private service; startup owns all external initialization."""
    app_config = config or AppConfig()
    container_ref = _ContainerRef()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = container_factory()
        container_ref.container = container
        app.state.container = container
        app.state.clients = container.clients
        app.state.services = container.services
        app.state.event_bus = container.event_bus
        app.state.event_handlers = container.event_handlers
        app.state.health_checks = container.health_checks
        try:
            yield
        finally:
            container.close()
            container_ref.container = None

    app = FastAPI(
        title=app_config.title,
        description=app_config.description,
        version=app_config.version,
        lifespan=lifespan,
        docs_url="/docs" if app_config.expose_docs else None,
        redoc_url="/redoc" if app_config.expose_docs else None,
        openapi_url="/openapi.json" if app_config.expose_docs else None,
    )
    app.include_router(create_health_router(_health_proxies(container_ref)))
    app.include_router(create_data_router(_service_proxies(container_ref)), prefix="/api")
    app.include_router(create_actions_router(_service_proxies(container_ref)), prefix="/api")
    app.include_router(
        create_workspace_router(_ContainerProxy(container_ref, lambda c: c.clients["database"])),
        prefix="/api",
    )
    app.add_middleware(
        WorkspaceAccessMiddleware,
        postgres=lambda: container_ref.get().clients["database"],
        lifecycle_service_secret=lambda: container_ref.get().lifecycle_service_secret,
    )
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
