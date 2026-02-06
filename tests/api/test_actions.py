"""Tests for POST /api/actions unified mutation endpoint."""

import pytest
from datetime import timedelta
from uuid import uuid4

from core.models import (
    CustomerCreate, TicketCreate, ServiceCreate, PricingType,
    LineItemCreate, AddressCreate, NoteCreate,
)
from utils.timezone import now_utc


# =============================================================================
# TEST DATA FIXTURES
# =============================================================================


@pytest.fixture
def sample_customer(as_test_user, customer_service):
    return customer_service.create(CustomerCreate(first_name="ActionTest", last_name="User"))


@pytest.fixture
def sample_address(as_test_user, address_service, sample_customer):
    return address_service.create(AddressCreate(
        customer_id=sample_customer.id,
        street="456 Oak Ave",
        city="Austin",
        state="TX",
        zip="78702",
    ))


@pytest.fixture
def sample_service(as_test_user, catalog_service):
    return catalog_service.create(ServiceCreate(
        name="Gutter Cleaning",
        pricing_type=PricingType.FIXED,
        default_price_cents=8000,
    ))


@pytest.fixture
def sample_ticket(as_test_user, ticket_service, sample_customer, sample_address):
    return ticket_service.create(TicketCreate(
        customer_id=sample_customer.id,
        address_id=sample_address.id,
        scheduled_at=now_utc() + timedelta(days=1),
    ))


# =============================================================================
# AUTHENTICATION & VALIDATION
# =============================================================================


class TestActionsAuthentication:

    def test_unauthenticated_returns_401(self, unauthed_client):
        response = unauthed_client.post("/api/actions", json={
            "domain": "customer",
            "action": "create",
            "data": {"first_name": "Nope"},
        })

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


class TestActionsValidation:

    def test_missing_domain_returns_422(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "action": "create",
            "data": {},
        })

        assert response.status_code == 422

    def test_missing_action_returns_422(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "data": {},
        })

        assert response.status_code == 422

    def test_unknown_domain_returns_400(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "spaceship",
            "action": "launch",
            "data": {},
        })

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "INVALID_REQUEST"
        assert "spaceship" in body["error"]["message"]

    def test_disallowed_action_returns_400(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "hack",
            "data": {},
        })

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "INVALID_REQUEST"
        assert "hack" in body["error"]["message"]


# =============================================================================
# CUSTOMER ACTIONS
# =============================================================================


class TestCustomerActions:

    def test_create_customer(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "create",
            "data": {"first_name": "Alice", "last_name": "Jones", "email": "alice@test.com"},
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["first_name"] == "Alice"
        assert data["last_name"] == "Jones"
        assert data["email"] == "alice@test.com"
        assert "id" in data

    def test_update_customer(self, client, sample_customer):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "update",
            "data": {"id": str(sample_customer.id), "first_name": "Updated"},
        })

        assert response.status_code == 200
        assert response.json()["data"]["first_name"] == "Updated"
        assert response.json()["data"]["id"] == str(sample_customer.id)

    def test_update_nonexistent_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "update",
            "data": {"id": str(uuid4()), "first_name": "Ghost"},
        })

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_delete_customer(self, client, sample_customer):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "delete",
            "data": {"id": str(sample_customer.id)},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent_customer_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "delete",
            "data": {"id": str(uuid4())},
        })

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


# =============================================================================
# TICKET ACTIONS
# =============================================================================


class TestTicketActions:

    def test_create_ticket(self, client, sample_customer, sample_address):
        scheduled = (now_utc() + timedelta(days=2)).isoformat()

        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "create",
            "data": {
                "customer_id": str(sample_customer.id),
                "address_id": str(sample_address.id),
                "scheduled_at": scheduled,
            },
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["customer_id"] == str(sample_customer.id)
        assert data["status"] == "scheduled"

    def test_clock_in(self, client, sample_ticket):
        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "clock_in",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "in_progress"
        assert response.json()["data"]["clock_in_at"] is not None

    def test_clock_in_already_clocked_returns_400(self, client, as_test_user, ticket_service, sample_ticket):
        ticket_service.clock_in(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "clock_in",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 400
        assert "already clocked in" in response.json()["error"]["message"]

    def test_clock_out(self, client, as_test_user, ticket_service, sample_ticket):
        ticket_service.clock_in(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "clock_out",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 200
        assert response.json()["data"]["clock_out_at"] is not None

    def test_clock_out_without_clock_in_returns_400(self, client, sample_ticket):
        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "clock_out",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 400
        assert "not clocked in" in response.json()["error"]["message"]

    def test_close(self, client, as_test_user, ticket_service, sample_ticket):
        ticket_service.clock_in(sample_ticket.id)
        ticket_service.clock_out(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "close",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "completed"
        assert response.json()["data"]["closed_at"] is not None

    def test_close_already_closed_returns_400(self, client, as_test_user, ticket_service, sample_ticket):
        ticket_service.clock_in(sample_ticket.id)
        ticket_service.clock_out(sample_ticket.id)
        ticket_service.close(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "close",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 400
        assert "already closed" in response.json()["error"]["message"]

    def test_cancel(self, client, sample_ticket):
        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "cancel",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "cancelled"

    def test_cancel_completed_returns_400(self, client, as_test_user, ticket_service, sample_ticket):
        ticket_service.clock_in(sample_ticket.id)
        ticket_service.clock_out(sample_ticket.id)
        ticket_service.close(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "cancel",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 400
        assert "cannot cancel" in response.json()["error"]["message"]

    def test_delete_ticket(self, client, sample_ticket):
        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "delete",
            "data": {"id": str(sample_ticket.id)},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent_ticket_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "ticket",
            "action": "delete",
            "data": {"id": str(uuid4())},
        })

        assert response.status_code == 404


# =============================================================================
# INVOICE ACTIONS
# =============================================================================


class TestInvoiceActions:

    def test_create_from_ticket(self, client, as_test_user, line_item_service, sample_ticket, sample_service):
        line_item_service.create(sample_ticket.id, LineItemCreate(service_id=sample_service.id))

        response = client.post("/api/actions", json={
            "domain": "invoice",
            "action": "create_from_ticket",
            "data": {"ticket_id": str(sample_ticket.id)},
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "draft"
        assert data["total_amount_cents"] == 8000

    def test_create_from_ticket_no_line_items_returns_400(self, client, sample_ticket):
        response = client.post("/api/actions", json={
            "domain": "invoice",
            "action": "create_from_ticket",
            "data": {"ticket_id": str(sample_ticket.id)},
        })

        assert response.status_code == 400
        assert "no line items" in response.json()["error"]["message"]

    def test_send_invoice(self, client, as_test_user, invoice_service, line_item_service, sample_ticket, sample_service):
        line_item_service.create(sample_ticket.id, LineItemCreate(service_id=sample_service.id))
        invoice = invoice_service.create_from_ticket(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "invoice",
            "action": "send",
            "data": {"id": str(invoice.id)},
        })

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "sent"
        assert response.json()["data"]["sent_at"] is not None

    def test_void_invoice(self, client, as_test_user, invoice_service, line_item_service, sample_ticket, sample_service):
        line_item_service.create(sample_ticket.id, LineItemCreate(service_id=sample_service.id))
        invoice = invoice_service.create_from_ticket(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "invoice",
            "action": "void",
            "data": {"id": str(invoice.id)},
        })

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "void"

    def test_record_payment(self, client, as_test_user, invoice_service, line_item_service, sample_ticket, sample_service):
        line_item_service.create(sample_ticket.id, LineItemCreate(service_id=sample_service.id))
        invoice = invoice_service.create_from_ticket(sample_ticket.id)
        invoice_service.send(invoice.id)

        response = client.post("/api/actions", json={
            "domain": "invoice",
            "action": "record_payment",
            "data": {"id": str(invoice.id), "amount_cents": 8000},
        })

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "paid"
        assert response.json()["data"]["amount_paid_cents"] == 8000


# =============================================================================
# LINE ITEM ACTIONS
# =============================================================================


class TestLineItemActions:

    def test_create_line_item(self, client, sample_ticket, sample_service):
        response = client.post("/api/actions", json={
            "domain": "line_item",
            "action": "create",
            "data": {
                "ticket_id": str(sample_ticket.id),
                "service_id": str(sample_service.id),
            },
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["ticket_id"] == str(sample_ticket.id)
        assert data["service_id"] == str(sample_service.id)
        assert data["total_price_cents"] == 8000

    def test_create_line_item_on_closed_ticket_returns_400(
        self, client, as_test_user, ticket_service, sample_ticket, sample_service
    ):
        ticket_service.clock_in(sample_ticket.id)
        ticket_service.clock_out(sample_ticket.id)
        ticket_service.close(sample_ticket.id)

        response = client.post("/api/actions", json={
            "domain": "line_item",
            "action": "create",
            "data": {
                "ticket_id": str(sample_ticket.id),
                "service_id": str(sample_service.id),
            },
        })

        assert response.status_code == 400
        assert "closed" in response.json()["error"]["message"].lower()

    def test_delete_line_item(self, client, as_test_user, line_item_service, sample_ticket, sample_service):
        li = line_item_service.create(sample_ticket.id, LineItemCreate(service_id=sample_service.id))

        response = client.post("/api/actions", json={
            "domain": "line_item",
            "action": "delete",
            "data": {"id": str(li.id)},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent_line_item_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "line_item",
            "action": "delete",
            "data": {"id": str(uuid4())},
        })

        assert response.status_code == 404


# =============================================================================
# NOTE ACTIONS
# =============================================================================


class TestNoteActions:

    def test_create_note(self, client, sample_customer):
        response = client.post("/api/actions", json={
            "domain": "note",
            "action": "create",
            "data": {
                "customer_id": str(sample_customer.id),
                "content": "Has two large dogs",
            },
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["customer_id"] == str(sample_customer.id)
        assert data["content"] == "Has two large dogs"

    def test_delete_note(self, client, as_test_user, note_service, sample_customer):
        note = note_service.create(NoteCreate(
            customer_id=sample_customer.id,
            content="Temporary note",
        ))

        response = client.post("/api/actions", json={
            "domain": "note",
            "action": "delete",
            "data": {"id": str(note.id)},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent_note_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "note",
            "action": "delete",
            "data": {"id": str(uuid4())},
        })

        assert response.status_code == 404


# =============================================================================
# ADDRESS ACTIONS
# =============================================================================


class TestAddressActions:

    def test_create_address(self, client, sample_customer):
        response = client.post("/api/actions", json={
            "domain": "address",
            "action": "create",
            "data": {
                "customer_id": str(sample_customer.id),
                "street": "789 Pine Rd",
                "city": "Dallas",
                "state": "TX",
                "zip": "75201",
            },
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["street"] == "789 Pine Rd"
        assert data["city"] == "Dallas"

    def test_update_address(self, client, sample_address):
        response = client.post("/api/actions", json={
            "domain": "address",
            "action": "update",
            "data": {"id": str(sample_address.id), "city": "Houston"},
        })

        assert response.status_code == 200
        assert response.json()["data"]["city"] == "Houston"
        assert response.json()["data"]["street"] == "456 Oak Ave"

    def test_update_nonexistent_address_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "address",
            "action": "update",
            "data": {"id": str(uuid4()), "city": "Nowhere"},
        })

        assert response.status_code == 404

    def test_delete_address(self, client, sample_address):
        response = client.post("/api/actions", json={
            "domain": "address",
            "action": "delete",
            "data": {"id": str(sample_address.id)},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent_address_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "address",
            "action": "delete",
            "data": {"id": str(uuid4())},
        })

        assert response.status_code == 404


# =============================================================================
# CATALOG (SERVICE) ACTIONS
# =============================================================================


class TestCatalogActions:

    def test_create_service(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "catalog",
            "action": "create",
            "data": {
                "name": "Pressure Washing",
                "pricing_type": "fixed",
                "default_price_cents": 12000,
            },
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["name"] == "Pressure Washing"
        assert data["default_price_cents"] == 12000

    def test_update_service(self, client, sample_service):
        response = client.post("/api/actions", json={
            "domain": "catalog",
            "action": "update",
            "data": {"id": str(sample_service.id), "name": "Premium Gutter Cleaning"},
        })

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Premium Gutter Cleaning"

    def test_delete_service(self, client, sample_service):
        response = client.post("/api/actions", json={
            "domain": "catalog",
            "action": "delete",
            "data": {"id": str(sample_service.id)},
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent_service_returns_404(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "catalog",
            "action": "delete",
            "data": {"id": str(uuid4())},
        })

        assert response.status_code == 404


# =============================================================================
# RESPONSE FORMAT
# =============================================================================


class TestActionsResponseFormat:

    def test_success_format(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "create",
            "data": {"first_name": "FormatTest"},
        })

        body = response.json()
        assert body["success"] is True
        assert body["data"] is not None
        assert body["error"] is None
        assert "timestamp" in body["meta"]
        assert "request_id" in body["meta"]

    def test_error_format(self, client, as_test_user):
        response = client.post("/api/actions", json={
            "domain": "customer",
            "action": "update",
            "data": {"id": str(uuid4()), "first_name": "Ghost"},
        })

        body = response.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "NOT_FOUND"
        assert isinstance(body["error"]["message"], str)
        assert "timestamp" in body["meta"]
