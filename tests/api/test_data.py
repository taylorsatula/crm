"""Tests for GET /api/data unified read endpoint."""

import pytest
from datetime import datetime, time, timezone, timedelta
from uuid import uuid4

from core.models import (
    CustomerCreate, TicketCreate, ServiceCreate, PricingType,
    LineItemCreate, NoteCreate, AddressCreate,
    ScheduledMessageCreate, MessageType, AttributeCreate,
)
from utils.timezone import now_utc


# =============================================================================
# TEST DATA FIXTURES
# =============================================================================


@pytest.fixture
def sample_customer(as_test_user, customer_service):
    return customer_service.create(CustomerCreate(first_name="Test", last_name="Customer"))


@pytest.fixture
def sample_address(as_test_user, address_service, sample_customer):
    return address_service.create(AddressCreate(
        customer_id=sample_customer.id,
        street="123 Main St",
        city="Austin",
        state="TX",
        zip="78701",
    ))


@pytest.fixture
def sample_ticket(as_test_user, ticket_service, sample_customer, sample_address):
    return ticket_service.create(TicketCreate(
        customer_id=sample_customer.id,
        address_id=sample_address.id,
        scheduled_at=now_utc() + timedelta(days=1),
    ))


@pytest.fixture
def sample_service(as_test_user, catalog_service):
    return catalog_service.create(ServiceCreate(
        name="Window Cleaning",
        pricing_type=PricingType.FIXED,
        default_price_cents=5000,
    ))


@pytest.fixture
def sample_line_item(as_test_user, line_item_service, sample_ticket, sample_service):
    return line_item_service.create(
        sample_ticket.id,
        LineItemCreate(service_id=sample_service.id),
    )


@pytest.fixture
def sample_note(as_test_user, note_service, sample_customer):
    return note_service.create(NoteCreate(
        customer_id=sample_customer.id,
        content="Test note content",
    ))


@pytest.fixture
def sample_message(as_test_user, message_service, sample_customer):
    return message_service.schedule(ScheduledMessageCreate(
        customer_id=sample_customer.id,
        message_type=MessageType.CUSTOM,
        subject="Follow up",
        body="Confirm next visit",
        scheduled_for=now_utc() + timedelta(days=1),
    ))


@pytest.fixture
def sample_attribute(as_test_user, attribute_service, sample_customer):
    return attribute_service.create(AttributeCreate(
        customer_id=sample_customer.id,
        key="gate_code",
        value="1234",
    ))


# =============================================================================
# AUTHENTICATION
# =============================================================================


class TestDataAuthentication:

    def test_unauthenticated_returns_401(self, unauthed_client):
        response = unauthed_client.get("/api/data", params={"type": "customers"})

        assert response.status_code == 401
        assert "X-Request-ID" in response.headers
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_AUTHENTICATED"
        assert body["meta"]["request_id"] == response.headers["X-Request-ID"]

    def test_authenticated_succeeds(self, client, as_test_user):
        response = client.get("/api/data", params={"type": "customers"})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["meta"]["request_id"] == response.headers["X-Request-ID"]


# =============================================================================
# VALIDATION
# =============================================================================


class TestDataValidation:

    def test_missing_type_returns_400(self, client, as_test_user):
        response = client.get("/api/data")

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "INVALID_REQUEST"
        assert "type" in body["error"]["message"].lower()
        assert body["meta"]["request_id"] == response.headers["X-Request-ID"]

    def test_unknown_type_returns_400(self, client, as_test_user):
        response = client.get("/api/data", params={"type": "unicorns"})

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "INVALID_REQUEST"


# =============================================================================
# CUSTOMERS
# =============================================================================


class TestDataCustomers:

    def test_list_customers(self, client, sample_customer):
        response = client.get("/api/data", params={"type": "customers"})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        customers = body["data"]
        assert len(customers) == 1
        assert customers[0]["id"] == str(sample_customer.id)
        assert customers[0]["first_name"] == "Test"
        assert customers[0]["last_name"] == "Customer"

    def test_get_customer_by_id(self, client, sample_customer):
        response = client.get("/api/data", params={
            "type": "customers",
            "id": str(sample_customer.id),
        })

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["id"] == str(sample_customer.id)
        assert body["data"]["first_name"] == "Test"

    def test_get_nonexistent_customer_returns_404(self, client, as_test_user):
        fake_id = str(uuid4())
        response = client.get("/api/data", params={
            "type": "customers",
            "id": fake_id,
        })

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_search_customers(self, client, sample_customer):
        response = client.get("/api/data", params={
            "type": "customers",
            "search": "Test",
        })

        assert response.status_code == 200
        results = response.json()["data"]
        assert len(results) == 1
        assert results[0]["first_name"] == "Test"

    def test_search_no_match_returns_empty(self, client, sample_customer):
        response = client.get("/api/data", params={
            "type": "customers",
            "search": "zzzznonexistent",
        })

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_list_customers_respects_limit(self, client, as_test_user, customer_service):
        for i in range(5):
            customer_service.create(CustomerCreate(first_name=f"Cust{i}"))

        response = client.get("/api/data", params={
            "type": "customers",
            "limit": "2",
        })

        assert response.status_code == 200
        assert len(response.json()["data"]) == 2

    def test_include_addresses(self, client, sample_customer, sample_address):
        response = client.get("/api/data", params={
            "type": "customers",
            "id": str(sample_customer.id),
            "include": "addresses",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == str(sample_customer.id)
        assert "addresses" in data
        assert len(data["addresses"]) == 1
        assert data["addresses"][0]["street"] == "123 Main St"
        assert data["addresses"][0]["city"] == "Austin"

    def test_include_customer_activity(
        self,
        client,
        as_test_user,
        sample_customer,
        sample_ticket,
        sample_note,
        sample_message,
        sample_attribute,
        invoice_service,
        sample_line_item,
    ):
        invoice = invoice_service.create_from_ticket(sample_ticket.id)

        response = client.get("/api/data", params={
            "type": "customers",
            "id": str(sample_customer.id),
            "include": "tickets,invoices,notes,messages,attributes",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == str(sample_customer.id)
        assert data["notes"] is None
        assert data["tickets"][0]["id"] == str(sample_ticket.id)
        assert data["invoices"][0]["id"] == str(invoice.id)
        assert data["note_items"][0]["id"] == str(sample_note.id)
        assert data["messages"][0]["id"] == str(sample_message.id)
        assert data["attributes"][0]["id"] == str(sample_attribute.id)


# =============================================================================
# TICKETS
# =============================================================================


class TestDataTickets:

    def test_list_tickets_for_customer(self, client, sample_ticket, sample_customer):
        response = client.get("/api/data", params={
            "type": "tickets",
            "customer_id": str(sample_customer.id),
        })

        assert response.status_code == 200
        tickets = response.json()["data"]
        assert len(tickets) == 1
        assert tickets[0]["id"] == str(sample_ticket.id)
        assert tickets[0]["customer_id"] == str(sample_customer.id)
        assert tickets[0]["status"] == "scheduled"

    def test_get_ticket_by_id(self, client, sample_ticket):
        response = client.get("/api/data", params={
            "type": "tickets",
            "id": str(sample_ticket.id),
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == str(sample_ticket.id)
        assert data["status"] == "scheduled"

    def test_get_nonexistent_ticket_returns_404(self, client, as_test_user):
        response = client.get("/api/data", params={
            "type": "tickets",
            "id": str(uuid4()),
        })

        assert response.status_code == 404

    def test_include_line_items(self, client, sample_ticket, sample_line_item):
        response = client.get("/api/data", params={
            "type": "tickets",
            "id": str(sample_ticket.id),
            "include": "line_items",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == str(sample_ticket.id)
        assert "line_items" in data
        assert len(data["line_items"]) == 1
        assert data["line_items"][0]["id"] == str(sample_line_item.id)
        assert data["line_items"][0]["total_price_cents"] == 5000

    def test_include_notes(self, client, as_test_user, sample_ticket, note_service):
        note = note_service.create(NoteCreate(
            ticket_id=sample_ticket.id,
            content="Ticket note here",
        ))

        response = client.get("/api/data", params={
            "type": "tickets",
            "id": str(sample_ticket.id),
            "include": "notes",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert "notes" in data
        assert "note_items" in data
        assert data["job_notes"] is None
        assert len(data["notes"]) == 1
        assert data["notes"][0]["content"] == "Ticket note here"

    def test_include_multiple(self, client, as_test_user, sample_ticket, sample_line_item, note_service):
        note_service.create(NoteCreate(
            ticket_id=sample_ticket.id,
            content="Multi-include note",
        ))

        response = client.get("/api/data", params={
            "type": "tickets",
            "id": str(sample_ticket.id),
            "include": "line_items,notes",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["line_items"]) == 1
        assert len(data["notes"]) == 1

    def test_include_pending_messages(self, client, as_test_user, sample_ticket, sample_customer, message_service):
        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=sample_customer.id,
            ticket_id=sample_ticket.id,
            message_type=MessageType.APPOINTMENT_REMINDER,
            subject="Reminder",
            scheduled_for=now_utc() + timedelta(hours=1),
        ))

        response = client.get("/api/data", params={
            "type": "tickets",
            "id": str(sample_ticket.id),
            "include": "messages",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["messages"]) == 1
        assert data["messages"][0]["id"] == str(message.id)

    def test_list_upcoming_ticket_packets(self, client, sample_ticket):
        response = client.get("/api/data", params={
            "type": "tickets",
            "filter": "upcoming",
        })

        assert response.status_code == 200
        rows = response.json()["data"]
        row = next(item for item in rows if item["ticket"]["id"] == str(sample_ticket.id))
        assert row["customer"]["display_name"] == "Test Customer"
        assert row["address"]["one_line"] == "123 Main St, Austin, TX, 78701"
        assert row["scope_summary"] == "No line items"


# =============================================================================
# CONVENIENCE ROUTES
# =============================================================================


class TestTicketsToday:

    def test_returns_todays_tickets(self, client, as_test_user, ticket_service, sample_customer, sample_address):
        today_at_10 = datetime.combine(
            now_utc().date(), time(10, 0), tzinfo=timezone.utc
        )
        created = ticket_service.create(TicketCreate(
            customer_id=sample_customer.id,
            address_id=sample_address.id,
            scheduled_at=today_at_10,
        ))

        response = client.get("/api/data/tickets/today")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1
        ids = [t["id"] for t in data]
        assert str(created.id) in ids

    def test_excludes_tomorrows_tickets(self, client, as_test_user, ticket_service, sample_customer, sample_address):
        tomorrow = now_utc() + timedelta(days=1)
        ticket_service.create(TicketCreate(
            customer_id=sample_customer.id,
            address_id=sample_address.id,
            scheduled_at=tomorrow,
        ))

        response = client.get("/api/data/tickets/today")

        assert response.status_code == 200
        assert response.json()["data"] == []


class TestTicketsCurrent:

    def test_returns_in_progress_ticket(self, client, as_test_user, ticket_service, sample_ticket):
        ticket_service.clock_in(sample_ticket.id)

        response = client.get("/api/data/tickets/current")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == str(sample_ticket.id)
        assert data["status"] == "in_progress"

    def test_returns_null_after_clock_out(self, client, as_test_user, ticket_service, sample_ticket):
        ticket_service.clock_in(sample_ticket.id)
        ticket_service.clock_out(sample_ticket.id)

        response = client.get("/api/data/tickets/current")

        assert response.status_code == 200
        assert response.json()["data"] is None

    def test_returns_null_when_none_in_progress(self, client, as_test_user):
        response = client.get("/api/data/tickets/current")

        assert response.status_code == 200
        assert response.json()["data"] is None


class TestControlSurfaceReadShapes:

    def test_today_returns_dense_operator_rows(
        self,
        client,
        as_test_user,
        ticket_service,
        line_item_service,
        message_service,
        invoice_service,
        sample_customer,
        sample_address,
        sample_service,
    ):
        today_at_10 = datetime.combine(
            now_utc().date(), time(10, 0), tzinfo=timezone.utc
        )
        ticket = ticket_service.create(TicketCreate(
            customer_id=sample_customer.id,
            address_id=sample_address.id,
            scheduled_at=today_at_10,
        ))
        line_item_service.create(ticket.id, LineItemCreate(service_id=sample_service.id))
        message_service.schedule(ScheduledMessageCreate(
            customer_id=sample_customer.id,
            ticket_id=ticket.id,
            message_type=MessageType.APPOINTMENT_CONFIRMATION,
            subject="Confirm",
            scheduled_for=now_utc() + timedelta(hours=1),
        ))
        invoice = invoice_service.create_from_ticket(ticket.id)

        response = client.get("/api/data/today")

        assert response.status_code == 200
        rows = response.json()["data"]
        row = next(item for item in rows if item["ticket"]["id"] == str(ticket.id))
        assert row["customer"]["display_name"] == "Test Customer"
        assert row["address"]["one_line"] == "123 Main St, Austin, TX, 78701"
        assert row["line_items"][0]["service_name"] == "Window Cleaning"
        assert row["scope_summary"] == "Window Cleaning"
        assert row["pending_message_count"] == 1
        assert row["invoice_summary"]["id"] == str(invoice.id)
        assert row["clock_state"] == "not_started"

    def test_ticket_packet_returns_operational_context(
        self,
        client,
        as_test_user,
        sample_ticket,
        sample_line_item,
        sample_customer,
        note_service,
        message_service,
        invoice_service,
    ):
        note = note_service.create(NoteCreate(
            ticket_id=sample_ticket.id,
            content="Bring ladder",
        ))
        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=sample_customer.id,
            ticket_id=sample_ticket.id,
            message_type=MessageType.APPOINTMENT_REMINDER,
            subject="Reminder",
            scheduled_for=now_utc() + timedelta(hours=1),
        ))
        invoice = invoice_service.create_from_ticket(sample_ticket.id)

        response = client.get(f"/api/data/tickets/{sample_ticket.id}/packet")

        assert response.status_code == 200
        packet = response.json()["data"]
        assert packet["ticket"]["id"] == str(sample_ticket.id)
        assert packet["customer"]["display_name"] == "Test Customer"
        assert packet["address"]["one_line"] == "123 Main St, Austin, TX, 78701"
        assert packet["line_items"][0]["id"] == str(sample_line_item.id)
        assert packet["notes"][0]["id"] == str(note.id)
        assert packet["pending_messages"][0]["id"] == str(message.id)
        assert packet["invoice_summary"]["id"] == str(invoice.id)

    def test_customer_dossier_returns_knowledge_clusters(
        self,
        client,
        as_test_user,
        sample_customer,
        sample_address,
        sample_ticket,
        sample_note,
        sample_message,
        sample_attribute,
        invoice_service,
        sample_line_item,
    ):
        invoice = invoice_service.create_from_ticket(sample_ticket.id)

        response = client.get(f"/api/data/customers/{sample_customer.id}/dossier")

        assert response.status_code == 200
        dossier = response.json()["data"]
        assert dossier["customer"]["display_name"] == "Test Customer"
        assert dossier["addresses"][0]["id"] == str(sample_address.id)
        assert dossier["attributes"][0]["id"] == str(sample_attribute.id)
        assert dossier["notes"][0]["id"] == str(sample_note.id)
        assert dossier["recent_tickets"][0]["id"] == str(sample_ticket.id)
        assert dossier["invoices"][0]["id"] == str(invoice.id)
        assert dossier["open_invoices"][0]["id"] == str(invoice.id)
        assert dossier["messages"][0]["id"] == str(sample_message.id)
        assert dossier["pending_messages"][0]["id"] == str(sample_message.id)


# =============================================================================
# SERVICES
# =============================================================================


class TestDataServices:

    def test_list_active_services(self, client, sample_service):
        response = client.get("/api/data", params={
            "type": "services",
            "filter": "active",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "Window Cleaning"
        assert data[0]["is_active"] is True

    def test_list_all_services(self, client, sample_service):
        response = client.get("/api/data", params={"type": "services"})

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(sample_service.id)


# =============================================================================
# INVOICES
# =============================================================================


class TestDataInvoices:

    def test_list_unpaid_invoices(self, client, as_test_user, invoice_service, sample_ticket, sample_line_item):
        invoice = invoice_service.create_from_ticket(sample_ticket.id)
        invoice_service.send(invoice.id)

        response = client.get("/api/data", params={
            "type": "invoices",
            "filter": "unpaid",
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(invoice.id)
        assert data[0]["status"] == "sent"
        assert data[0]["total_amount_cents"] == 5000

    def test_get_invoice_by_id(self, client, as_test_user, invoice_service, sample_ticket, sample_line_item):
        invoice = invoice_service.create_from_ticket(sample_ticket.id)

        response = client.get("/api/data", params={
            "type": "invoices",
            "id": str(invoice.id),
        })

        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(invoice.id)

    def test_list_invoices_for_customer(
        self, client, as_test_user, invoice_service, sample_customer, sample_ticket, sample_line_item
    ):
        invoice = invoice_service.create_from_ticket(sample_ticket.id)

        response = client.get("/api/data", params={
            "type": "invoices",
            "customer_id": str(sample_customer.id),
        })

        assert response.status_code == 200
        assert response.json()["data"][0]["id"] == str(invoice.id)


# =============================================================================
# MESSAGES
# =============================================================================


class TestDataMessages:

    def test_get_message_by_id(self, client, sample_message):
        response = client.get("/api/data", params={
            "type": "messages",
            "id": str(sample_message.id),
        })

        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(sample_message.id)

    def test_list_messages_for_customer(self, client, sample_message, sample_customer):
        response = client.get("/api/data", params={
            "type": "messages",
            "customer_id": str(sample_customer.id),
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(sample_message.id)

    def test_list_pending_messages_for_ticket(
        self, client, as_test_user, message_service, sample_customer, sample_ticket
    ):
        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=sample_customer.id,
            ticket_id=sample_ticket.id,
            message_type=MessageType.APPOINTMENT_CONFIRMATION,
            scheduled_for=now_utc() + timedelta(hours=1),
        ))

        response = client.get("/api/data", params={
            "type": "messages",
            "ticket_id": str(sample_ticket.id),
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(message.id)


# =============================================================================
# NOTES
# =============================================================================


class TestDataNotes:

    def test_list_notes_for_customer(self, client, sample_note, sample_customer):
        response = client.get("/api/data", params={
            "type": "notes",
            "customer_id": str(sample_customer.id),
        })

        assert response.status_code == 200
        assert response.json()["data"][0]["id"] == str(sample_note.id)


# =============================================================================
# ATTRIBUTES
# =============================================================================


class TestDataAttributes:

    def test_get_attribute_by_id(self, client, sample_attribute):
        response = client.get("/api/data", params={
            "type": "attributes",
            "id": str(sample_attribute.id),
        })

        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(sample_attribute.id)

    def test_list_attributes_for_customer(self, client, sample_attribute, sample_customer):
        response = client.get("/api/data", params={
            "type": "attributes",
            "customer_id": str(sample_customer.id),
        })

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["key"] == "gate_code"


# =============================================================================
# RESPONSE FORMAT
# =============================================================================


class TestResponseFormat:

    def test_success_has_all_fields(self, client, as_test_user):
        response = client.get("/api/data", params={"type": "customers"})

        body = response.json()
        assert body["success"] is True
        assert body["data"] == []
        assert body["error"] is None
        assert "timestamp" in body["meta"]
        assert "request_id" in body["meta"]

    def test_error_has_all_fields(self, client, as_test_user):
        response = client.get("/api/data", params={
            "type": "customers",
            "id": str(uuid4()),
        })

        body = response.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "NOT_FOUND"
        assert isinstance(body["error"]["message"], str)
        assert "timestamp" in body["meta"]
        assert "request_id" in body["meta"]
