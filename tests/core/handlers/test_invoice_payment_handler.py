"""Tests for invoice payment handler.

On InvoicePaid: schedule a receipt/thank-you message to the customer.

Uses real MessageService against the DB — no mocks.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from core.events import InvoicePaid
from core.handlers.invoice_payment_handler import handle_invoice_paid
from core.models import (
    CustomerCreate, TicketCreate,
    ScheduledMessageCreate, MessageType, MessageStatus,
)
from utils.timezone import now_utc


@pytest.fixture
def message_service(db):
    from core.services.message_service import MessageService
    from core.audit import AuditLogger
    return MessageService(db, AuditLogger(db))


@pytest.fixture
def customer_service(db, event_bus):
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger
    return CustomerService(db, AuditLogger(db), event_bus)


@pytest.fixture
def ticket_service(db, event_bus):
    from core.services.ticket_service import TicketService
    from core.audit import AuditLogger
    return TicketService(db, AuditLogger(db), event_bus)


@pytest.fixture
def address_service(db):
    from core.services.address_service import AddressService
    from core.audit import AuditLogger
    return AddressService(db, AuditLogger(db))


@pytest.fixture
def line_item_service(db):
    from core.services.line_item_service import LineItemService
    from core.audit import AuditLogger
    return LineItemService(db, AuditLogger(db))


@pytest.fixture
def catalog_service(db):
    from core.services.catalog_service import CatalogService
    from core.audit import AuditLogger
    return CatalogService(db, AuditLogger(db))


@pytest.fixture
def invoice_service(db, event_bus):
    from core.services.invoice_service import InvoiceService
    from core.audit import AuditLogger
    return InvoiceService(db, AuditLogger(db), event_bus)


@pytest.fixture
def test_customer(as_test_user, customer_service):
    return customer_service.create(CustomerCreate(
        first_name="Payment", last_name="Test", email="pay@test.com"
    ))


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    from core.models import AddressCreate
    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="300 Payment Ln", city="Austin", state="TX", zip="78703"
    ))


@pytest.fixture
def test_invoice(
    as_test_user, ticket_service, invoice_service,
    line_item_service, catalog_service,
    test_customer, test_address
):
    """Create a real invoice from a ticket with line items."""
    from core.models import ServiceCreate, PricingType, LineItemCreate

    service = catalog_service.create(ServiceCreate(
        name="Window Cleaning",
        pricing_type=PricingType.FIXED,
        default_price_cents=10000,
    ))

    ticket = ticket_service.create(TicketCreate(
        customer_id=test_customer.id,
        address_id=test_address.id,
        scheduled_at=now_utc() + timedelta(days=1),
    ))

    line_item_service.create(ticket.id, LineItemCreate(
        service_id=service.id,
        quantity=1,
        total_price_cents=10000,
    ))

    invoice = invoice_service.create_from_ticket(ticket.id)
    invoice = invoice_service.send(invoice.id)
    invoice = invoice_service.record_payment(invoice.id, invoice.total_amount_cents)
    return invoice


@pytest.fixture
def handler(message_service):
    return handle_invoice_paid(message_service)


class TestInvoicePaymentHandler:

    def test_schedules_receipt_message_in_db(
        self, db, as_test_user, handler, message_service, test_customer, test_invoice
    ):
        event = InvoicePaid(invoice=test_invoice)
        handler(event)

        messages = message_service.list_for_customer(test_customer.id)
        receipt_messages = [
            m for m in messages
            if test_invoice.invoice_number in (m.body or "")
        ]

        assert len(receipt_messages) == 1
        msg = receipt_messages[0]
        assert msg.customer_id == test_customer.id
        assert msg.message_type == MessageType.CUSTOM
        assert msg.status == MessageStatus.PENDING
        assert test_invoice.invoice_number in msg.body

    def test_receipt_references_correct_invoice_number(
        self, db, as_test_user, handler, message_service, test_customer, test_invoice
    ):
        event = InvoicePaid(invoice=test_invoice)
        handler(event)

        messages = message_service.list_for_customer(test_customer.id)
        assert any(test_invoice.invoice_number in (m.body or "") for m in messages)

    def test_schedules_exactly_one_message(
        self, db, as_test_user, handler, message_service, test_customer, test_invoice
    ):
        # Count before
        before = len(message_service.list_for_customer(test_customer.id))

        event = InvoicePaid(invoice=test_invoice)
        handler(event)

        after = len(message_service.list_for_customer(test_customer.id))
        assert after - before == 1
