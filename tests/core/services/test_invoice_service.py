"""Tests for InvoiceService."""

import pytest
from uuid import uuid4
from datetime import timedelta

from utils.timezone import now_utc


@pytest.fixture
def invoice_service(db):
    """InvoiceService with real DB."""
    from core.services.invoice_service import InvoiceService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return InvoiceService(db, audit)


@pytest.fixture
def ticket_service(db):
    """TicketService for test setup."""
    from core.services.ticket_service import TicketService
    from core.audit import AuditLogger

    return TicketService(db, AuditLogger(db))


@pytest.fixture
def line_item_service(db):
    """LineItemService for test setup."""
    from core.services.line_item_service import LineItemService
    from core.audit import AuditLogger

    return LineItemService(db, AuditLogger(db))


@pytest.fixture
def customer_service(db):
    """CustomerService for test setup."""
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger

    return CustomerService(db, AuditLogger(db))


@pytest.fixture
def address_service(db):
    """AddressService for test setup."""
    from core.services.address_service import AddressService
    from core.audit import AuditLogger

    return AddressService(db, AuditLogger(db))


@pytest.fixture
def catalog_service(db):
    """CatalogService for test setup."""
    from core.services.catalog_service import CatalogService
    from core.audit import AuditLogger

    return CatalogService(db, AuditLogger(db))


@pytest.fixture
def test_customer(as_test_user, customer_service):
    """Create a test customer."""
    from core.models import CustomerCreate

    customer = customer_service.create(CustomerCreate(first_name="Invoice", last_name="Test"))
    yield customer
    customer_service.delete(customer.id)


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    """Create a test address."""
    from core.models import AddressCreate

    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="123 Invoice Lane",
        city="Austin",
        state="TX",
        zip="78704"
    ))


@pytest.fixture
def test_service(as_test_user, catalog_service):
    """Create a test service in the catalog."""
    from core.models import ServiceCreate, PricingType

    service = catalog_service.create(ServiceCreate(
        name="Invoice Test Service",
        pricing_type=PricingType.FIXED,
        default_price_cents=10000  # $100.00
    ))
    yield service
    catalog_service.delete(service.id)


@pytest.fixture
def test_ticket_with_items(as_test_user, ticket_service, line_item_service, test_customer, test_address, test_service):
    """Create a test ticket with line items."""
    from core.models import TicketCreate, LineItemCreate

    ticket = ticket_service.create(TicketCreate(
        customer_id=test_customer.id,
        address_id=test_address.id,
        scheduled_at=now_utc() + timedelta(days=1)
    ))

    # Add some line items
    line_item_service.create(ticket.id, LineItemCreate(
        service_id=test_service.id,
        quantity=2,
        unit_price_cents=10000,
        total_price_cents=20000  # $200
    ))
    line_item_service.create(ticket.id, LineItemCreate(
        service_id=test_service.id,
        quantity=1,
        total_price_cents=5000  # $50
    ))

    yield ticket
    ticket_service.delete(ticket.id)


class TestInvoiceCreate:
    """Tests for InvoiceService.create_from_ticket."""

    def test_creates_invoice_from_ticket(self, db, as_test_user, invoice_service, test_ticket_with_items, test_customer):
        """Creates invoice from ticket line items."""
        from core.models import InvoiceStatus

        invoice = invoice_service.create_from_ticket(
            test_ticket_with_items.id,
            tax_rate_bps=825  # 8.25% sales tax
        )

        assert invoice.ticket_id == test_ticket_with_items.id
        assert invoice.customer_id == test_customer.id
        assert invoice.status == InvoiceStatus.DRAFT
        assert invoice.subtotal_cents == 25000  # $250 (200 + 50)
        assert invoice.tax_rate_bps == 825
        # Tax should be ~$20.63 (25000 * 825 / 10000)
        assert invoice.tax_amount_cents == 2062
        assert invoice.total_amount_cents == 27062

    def test_invoice_starts_as_draft(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """New invoices start in DRAFT status."""
        from core.models import InvoiceStatus

        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)

        assert invoice.status == InvoiceStatus.DRAFT
        assert invoice.issued_at is None
        assert invoice.sent_at is None
        assert invoice.paid_at is None

    def test_generates_invoice_number(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Invoice number is auto-generated."""
        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)

        assert invoice.invoice_number is not None
        assert len(invoice.invoice_number) > 0

    def test_rejects_ticket_without_items(self, db, as_test_user, invoice_service, ticket_service, test_customer, test_address):
        """Cannot create invoice from ticket with no line items."""
        from core.models import TicketCreate

        empty_ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        with pytest.raises(ValueError, match="no line items"):
            invoice_service.create_from_ticket(empty_ticket.id)

        ticket_service.delete(empty_ticket.id)


class TestInvoiceGet:
    """Tests for InvoiceService.get_by_id."""

    def test_gets_invoice(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Gets invoice by ID."""
        created = invoice_service.create_from_ticket(test_ticket_with_items.id)

        fetched = invoice_service.get_by_id(created.id)

        assert fetched is not None
        assert fetched.id == created.id

    def test_returns_none_for_missing(self, db, as_test_user, invoice_service):
        """Returns None for non-existent invoice."""
        result = invoice_service.get_by_id(uuid4())
        assert result is None


class TestInvoiceSend:
    """Tests for InvoiceService.send."""

    def test_send_marks_sent(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Sending invoice updates status and timestamps."""
        from core.models import InvoiceStatus

        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)

        sent = invoice_service.send(invoice.id)

        assert sent.status == InvoiceStatus.SENT
        assert sent.sent_at is not None
        assert sent.issued_at is not None

    def test_cannot_send_void_invoice(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Cannot send voided invoice."""
        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)
        invoice_service.void(invoice.id)

        with pytest.raises(ValueError, match="voided"):
            invoice_service.send(invoice.id)


class TestInvoicePayment:
    """Tests for InvoiceService payment methods."""

    def test_record_payment_partial(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Recording partial payment updates status to PARTIAL."""
        from core.models import InvoiceStatus

        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)
        invoice_service.send(invoice.id)

        # Pay half
        partial_amount = invoice.total_amount_cents // 2
        updated = invoice_service.record_payment(invoice.id, partial_amount)

        assert updated.amount_paid_cents == partial_amount
        assert updated.status == InvoiceStatus.PARTIAL

    def test_record_payment_full(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Recording full payment marks as PAID."""
        from core.models import InvoiceStatus

        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)
        invoice_service.send(invoice.id)

        updated = invoice_service.record_payment(invoice.id, invoice.total_amount_cents)

        assert updated.status == InvoiceStatus.PAID
        assert updated.paid_at is not None
        assert updated.amount_paid_cents == invoice.total_amount_cents

    def test_multiple_payments(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Multiple payments accumulate."""
        from core.models import InvoiceStatus

        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)
        invoice_service.send(invoice.id)

        # First payment
        first_payment = 10000
        invoice_service.record_payment(invoice.id, first_payment)

        # Second payment - pay the rest
        remaining = invoice.total_amount_cents - first_payment
        updated = invoice_service.record_payment(invoice.id, remaining)

        assert updated.amount_paid_cents == invoice.total_amount_cents
        assert updated.status == InvoiceStatus.PAID


class TestInvoiceVoid:
    """Tests for InvoiceService.void."""

    def test_void_invoice(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Voiding invoice sets status and timestamp."""
        from core.models import InvoiceStatus

        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)

        voided = invoice_service.void(invoice.id)

        assert voided.status == InvoiceStatus.VOID
        assert voided.voided_at is not None

    def test_cannot_void_paid_invoice(self, db, as_test_user, invoice_service, test_ticket_with_items):
        """Cannot void paid invoice."""
        invoice = invoice_service.create_from_ticket(test_ticket_with_items.id)
        invoice_service.send(invoice.id)
        invoice_service.record_payment(invoice.id, invoice.total_amount_cents)

        with pytest.raises(ValueError, match="paid"):
            invoice_service.void(invoice.id)


class TestInvoiceList:
    """Tests for InvoiceService list methods."""

    def test_list_for_customer(self, db, as_test_user, invoice_service, test_ticket_with_items, test_customer):
        """Lists invoices for a customer."""
        invoice_service.create_from_ticket(test_ticket_with_items.id)

        invoices = invoice_service.list_for_customer(test_customer.id)

        assert len(invoices) >= 1
        assert all(inv.customer_id == test_customer.id for inv in invoices)
