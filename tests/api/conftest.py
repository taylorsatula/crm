"""API test fixtures — authenticated TestClient with real database services."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from api.errors import register_error_handlers
from api.middleware import RequestIDMiddleware
from auth.security_middleware import AuthMiddleware
from auth.session import SessionManager
from auth.types import Session
from core.audit import AuditLogger
from core.services.customer_service import CustomerService
from core.services.ticket_service import TicketService
from core.services.catalog_service import CatalogService
from core.services.line_item_service import LineItemService
from core.services.invoice_service import InvoiceService
from core.services.note_service import NoteService
from core.services.attribute_service import AttributeService
from core.services.message_service import MessageService
from core.services.address_service import AddressService
from utils.timezone import now_utc


# =============================================================================
# SERVICE FIXTURES
# =============================================================================


@pytest.fixture
def audit(db):
    return AuditLogger(db)


@pytest.fixture
def customer_service(db, audit):
    return CustomerService(db, audit)


@pytest.fixture
def ticket_service(db, audit):
    return TicketService(db, audit)


@pytest.fixture
def catalog_service(db, audit):
    return CatalogService(db, audit)


@pytest.fixture
def line_item_service(db, audit):
    return LineItemService(db, audit)


@pytest.fixture
def invoice_service(db, audit):
    return InvoiceService(db, audit)


@pytest.fixture
def note_service(db, audit):
    return NoteService(db, audit)


@pytest.fixture
def attribute_service(db, audit):
    return AttributeService(db, audit)


@pytest.fixture
def message_service(db, audit):
    return MessageService(db, audit)


@pytest.fixture
def address_service(db, audit):
    return AddressService(db, audit)


# =============================================================================
# SERVICES DICT
# =============================================================================


@pytest.fixture
def services(
    customer_service,
    ticket_service,
    catalog_service,
    line_item_service,
    invoice_service,
    note_service,
    attribute_service,
    message_service,
    address_service,
):
    return {
        "customer": customer_service,
        "ticket": ticket_service,
        "catalog": catalog_service,
        "line_item": line_item_service,
        "invoice": invoice_service,
        "note": note_service,
        "attribute": attribute_service,
        "message": message_service,
        "address": address_service,
    }


# =============================================================================
# AUTH FIXTURES
# =============================================================================


@pytest.fixture
def mock_session_manager(test_user_id):
    now = now_utc()
    mock = Mock(spec=SessionManager)
    mock.validate_session.return_value = Session(
        token="test-token",
        user_id=test_user_id,
        created_at=now,
        expires_at=now + timedelta(hours=24),
        last_activity_at=now,
    )
    return mock


# =============================================================================
# APP & CLIENT FIXTURES
# =============================================================================


@pytest.fixture
def app(mock_session_manager, services):
    """FastAPI app with auth middleware, error handlers, and data/actions routes."""
    from api.data import create_data_router
    from api.actions import create_actions_router

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(AuthMiddleware, session_manager=mock_session_manager)
    register_error_handlers(app)

    app.include_router(create_data_router(services), prefix="/api")
    app.include_router(create_actions_router(services), prefix="/api")

    return app


@pytest.fixture
def client(app):
    """Authenticated test client."""
    c = TestClient(app, raise_server_exceptions=False)
    c.cookies.set("session_token", "test-token")
    return c


@pytest.fixture
def unauthed_client(app):
    """Unauthenticated test client (no session cookie)."""
    return TestClient(app, raise_server_exceptions=False)
