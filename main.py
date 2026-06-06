"""FastAPI application assembly."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.actions import create_actions_router
from api.data import create_data_router
from api.errors import register_error_handlers
from api.health import create_health_router
from api.middleware import RequestIDMiddleware
from auth.api import create_auth_router
from auth.config import AuthConfig
from auth.database import AuthDatabase
from auth.rate_limiter import RateLimiter
from auth.security_logger import SecurityLogger
from auth.security_middleware import AuthMiddleware
from auth.service import AuthService
from auth.session import SessionManager
from clients.email_client import EmailGatewayClient
from clients.llm_client import LLMClient
from clients.postgres_client import PostgresClient
from clients.valkey_client import ValkeyClient
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


# TODO: Before production, replace this refinement-mode no-cache policy with
# fingerprinted frontend assets and long-lived caching for immutable files.
FRONTEND_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, max-age=0, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@dataclass
class AppContainer:
    """Runtime dependencies assembled during application startup."""

    clients: dict[str, Any]
    auth_components: dict[str, Any]
    services: dict[str, Any]
    event_bus: EventBus
    event_handlers: dict[str, Callable]
    health_checks: dict[str, Any]
    auth_service: AuthService
    session_manager: SessionManager

    def close(self) -> None:
        """Close external client connections owned by the app."""
        self.clients["database"].close()
        self.clients["cache"].close()


class _ContainerRef:
    def __init__(self):
        self.container: Any | None = None

    def get(self) -> Any:
        if self.container is None:
            raise RuntimeError("Application container has not started")
        return self.container


class _ContainerProxy:
    def __init__(self, ref: _ContainerRef, resolver: Callable[[Any], Any]):
        self._ref = ref
        self._resolver = resolver

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolver(self._ref.get()), name)


class NoCacheStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path: Any,
        stat_result: Any,
        scope: dict[str, Any],
        status_code: int = 200,
    ) -> FileResponse:
        return FileResponse(
            full_path,
            status_code=status_code,
            stat_result=stat_result,
            headers=FRONTEND_NO_CACHE_HEADERS,
        )


def _service_proxies(ref: _ContainerRef) -> dict[str, Any]:
    service_names = [
        "customer",
        "ticket",
        "catalog",
        "line_item",
        "invoice",
        "note",
        "attribute",
        "message",
        "address",
    ]
    return {
        name: _ContainerProxy(ref, lambda container, key=name: container.services[key])
        for name in service_names
    }


def _health_proxies(ref: _ContainerRef) -> dict[str, Any]:
    check_names = ["database", "cache", "vault", "llm", "email"]
    return {
        name: _ContainerProxy(ref, lambda container, key=name: container.health_checks[key])
        for name in check_names
    }


def wire_event_handlers(
    event_bus: EventBus,
    extractor: AttributeExtractor,
    services: dict[str, Any],
) -> dict[str, Callable]:
    """Subscribe domain event handlers to the in-process event bus."""
    handlers = {
        "TicketCompleted": handle_ticket_completed(
            extractor,
            services["attribute"],
            services["note"],
        ),
        "TicketCancelled": handle_ticket_cancelled(services["message"]),
        "InvoicePaid": handle_invoice_paid(services["message"]),
    }

    for event_name, handler in handlers.items():
        event_bus.subscribe(event_name, handler)

    return handlers


def build_app_container() -> AppContainer:
    """Build the production application container from Vault-backed config."""
    load_dotenv(override=True)

    vault = VaultClient()

    postgres = PostgresClient(vault.get_secret("database", "url"))
    valkey = ValkeyClient(vault.get_secret("valkey", "url"))

    email_config = {
        "gateway_url": vault.get_secret("email", "gateway_url"),
        "api_key": vault.get_secret("email", "api_key"),
        "hmac_secret": vault.get_secret("email", "hmac_secret"),
        "health_url": vault.get_secret("email", "health_url"),
    }
    email_client = EmailGatewayClient(**email_config)

    llm = LLMClient(**vault.get_llm_config())

    auth_config = AuthConfig()
    auth_db = AuthDatabase(postgres)
    session_manager = SessionManager(valkey, auth_config)
    rate_limiter = RateLimiter(valkey, auth_config)
    security_logger = SecurityLogger(postgres)
    auth_service = AuthService(
        config=auth_config,
        auth_db=auth_db,
        session_manager=session_manager,
        rate_limiter=rate_limiter,
        email_client=email_client,
        security_logger=security_logger,
    )

    audit = AuditLogger(postgres)
    event_bus = EventBus()
    extractor = AttributeExtractor(llm)

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
    }
    event_handlers = wire_event_handlers(event_bus, extractor, services)

    clients = {
        "database": postgres,
        "cache": valkey,
        "vault": vault,
        "llm": llm,
        "email": email_client,
    }

    return AppContainer(
        clients=clients,
        auth_components={
            "config": auth_config,
            "database": auth_db,
            "session_manager": session_manager,
            "rate_limiter": rate_limiter,
            "security_logger": security_logger,
        },
        services=services,
        event_bus=event_bus,
        event_handlers=event_handlers,
        health_checks=clients,
        auth_service=auth_service,
        session_manager=session_manager,
    )


def create_app(
    *,
    container_factory: Callable[[], Any] = build_app_container,
    config: AppConfig | None = None,
) -> FastAPI:
    """Create the FastAPI app and defer external startup to lifespan."""
    app_config = config or AppConfig()
    container_ref = _ContainerRef()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = container_factory()
        container_ref.container = container
        app.state.container = container
        app.state.clients = getattr(container, "clients", {})
        app.state.auth_components = getattr(container, "auth_components", {})
        app.state.auth_service = container.auth_service
        app.state.services = container.services
        app.state.event_bus = container.event_bus
        app.state.event_handlers = getattr(container, "event_handlers", {})
        app.state.health_checks = container.health_checks

        try:
            yield
        finally:
            close = getattr(container, "close", None)
            if close is not None:
                close()
            container_ref.container = None

    app = FastAPI(
        title=app_config.title,
        description=app_config.description,
        version=app_config.version,
        lifespan=lifespan,
    )

    @app.get("/", include_in_schema=False)
    async def app_shell():
        return FileResponse(
            app_config.static_dir / "index.html",
            headers=FRONTEND_NO_CACHE_HEADERS,
        )

    app.include_router(create_health_router(_health_proxies(container_ref)))
    app.include_router(create_data_router(_service_proxies(container_ref)), prefix="/api")
    app.include_router(create_actions_router(_service_proxies(container_ref)), prefix="/api")
    app.include_router(
        create_auth_router(_ContainerProxy(container_ref, lambda c: c.auth_service)),
        prefix="/auth",
    )

    app.add_middleware(
        AuthMiddleware,
        session_manager=_ContainerProxy(container_ref, lambda c: c.session_manager),
    )
    app.add_middleware(RequestIDMiddleware)

    register_error_handlers(app)

    app.mount(
        "/assets",
        NoCacheStaticFiles(directory=app_config.static_dir / "assets"),
        name="assets",
    )

    return app


app = create_app()
