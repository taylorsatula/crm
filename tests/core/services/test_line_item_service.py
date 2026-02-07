"""Tests for LineItemService."""

import pytest
from uuid import uuid4
from datetime import timedelta

from utils.timezone import now_utc


@pytest.fixture
def line_item_service(db):
    """LineItemService with real DB."""
    from core.services.line_item_service import LineItemService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return LineItemService(db, audit)


@pytest.fixture
def ticket_service(db, event_bus):
    """TicketService for test setup."""
    from core.services.ticket_service import TicketService
    from core.audit import AuditLogger

    return TicketService(db, AuditLogger(db), event_bus)


@pytest.fixture
def customer_service(db, event_bus):
    """CustomerService for test setup."""
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger

    return CustomerService(db, AuditLogger(db), event_bus)


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

    customer = customer_service.create(CustomerCreate(first_name="LineItem", last_name="Test"))
    yield customer
    customer_service.delete(customer.id)


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    """Create a test address."""
    from core.models import AddressCreate

    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="456 Line Item St",
        city="Austin",
        state="TX",
        zip="78702"
    ))


@pytest.fixture
def test_ticket(as_test_user, ticket_service, test_customer, test_address):
    """Create a test ticket."""
    from core.models import TicketCreate

    ticket = ticket_service.create(TicketCreate(
        customer_id=test_customer.id,
        address_id=test_address.id,
        scheduled_at=now_utc() + timedelta(days=1)
    ))
    yield ticket
    ticket_service.delete(ticket.id)


@pytest.fixture
def test_service(as_test_user, catalog_service):
    """Create a test service in the catalog."""
    from core.models import ServiceCreate, PricingType

    service = catalog_service.create(ServiceCreate(
        name="Window Cleaning",
        pricing_type=PricingType.FIXED,
        default_price_cents=5000  # $50.00
    ))
    yield service
    catalog_service.delete(service.id)


class TestLineItemCreate:
    """Tests for LineItemService.create."""

    def test_creates_line_item(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """Creates line item with provided data."""
        from core.models import LineItemCreate

        data = LineItemCreate(
            service_id=test_service.id,
            quantity=2,
            unit_price_cents=5000,
            total_price_cents=10000
        )

        line_item = line_item_service.create(test_ticket.id, data)

        assert line_item.ticket_id == test_ticket.id
        assert line_item.service_id == test_service.id
        assert line_item.quantity == 2
        assert line_item.unit_price_cents == 5000
        assert line_item.total_price_cents == 10000

    def test_computes_total_from_unit_price(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """Total is computed when only unit_price_cents is provided."""
        from core.models import LineItemCreate

        data = LineItemCreate(
            service_id=test_service.id,
            quantity=3,
            unit_price_cents=1500  # $15 each, total should be $45 (4500 cents)
        )

        line_item = line_item_service.create(test_ticket.id, data)

        assert line_item.total_price_cents == 4500

    def test_uses_service_default_price(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """Uses service's default price when no price specified."""
        from core.models import LineItemCreate

        data = LineItemCreate(service_id=test_service.id)

        line_item = line_item_service.create(test_ticket.id, data)

        # test_service has default_price_cents=5000
        assert line_item.total_price_cents == 5000

    def test_rejects_closed_ticket(self, db, as_test_user, line_item_service, ticket_service, test_ticket, test_service):
        """Cannot add line items to closed tickets."""
        from core.models import LineItemCreate

        # Close the ticket
        ticket_service.clock_in(test_ticket.id)
        ticket_service.clock_out(test_ticket.id)
        ticket_service.close(test_ticket.id)

        with pytest.raises(ValueError, match="closed"):
            line_item_service.create(test_ticket.id, LineItemCreate(
                service_id=test_service.id,
                total_price_cents=5000
            ))

    def test_rejects_cancelled_ticket(self, db, as_test_user, line_item_service, ticket_service, test_ticket, test_service):
        """Cannot add line items to cancelled tickets."""
        from core.models import LineItemCreate

        ticket_service.cancel(test_ticket.id)

        with pytest.raises(ValueError, match="cancelled"):
            line_item_service.create(test_ticket.id, LineItemCreate(
                service_id=test_service.id,
                total_price_cents=5000
            ))


class TestLineItemGet:
    """Tests for LineItemService.get_by_id."""

    def test_gets_line_item(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """Gets line item by ID."""
        from core.models import LineItemCreate

        created = line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            total_price_cents=5000
        ))

        fetched = line_item_service.get_by_id(created.id)

        assert fetched is not None
        assert fetched.id == created.id

    def test_returns_none_for_missing(self, db, as_test_user, line_item_service):
        """Returns None for non-existent line item."""
        result = line_item_service.get_by_id(uuid4())
        assert result is None


class TestLineItemUpdate:
    """Tests for LineItemService.update."""

    def test_updates_quantity(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """Updates line item quantity."""
        from core.models import LineItemCreate, LineItemUpdate

        line_item = line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            quantity=1,
            unit_price_cents=5000,
            total_price_cents=5000
        ))

        updated = line_item_service.update(line_item.id, LineItemUpdate(
            quantity=3,
            total_price_cents=15000
        ))

        assert updated.quantity == 3
        assert updated.total_price_cents == 15000

    def test_updates_description(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """Updates line item description."""
        from core.models import LineItemCreate, LineItemUpdate

        line_item = line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            total_price_cents=5000
        ))

        updated = line_item_service.update(line_item.id, LineItemUpdate(
            description="Custom window cleaning for storefront"
        ))

        assert updated.description == "Custom window cleaning for storefront"

    def test_rejects_closed_ticket_update(self, db, as_test_user, line_item_service, ticket_service, test_ticket, test_service):
        """Cannot update line items on closed tickets."""
        from core.models import LineItemCreate, LineItemUpdate

        line_item = line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            total_price_cents=5000
        ))

        # Close the ticket
        ticket_service.clock_in(test_ticket.id)
        ticket_service.clock_out(test_ticket.id)
        ticket_service.close(test_ticket.id)

        with pytest.raises(ValueError, match="closed"):
            line_item_service.update(line_item.id, LineItemUpdate(quantity=5))


class TestLineItemDelete:
    """Tests for LineItemService.delete."""

    def test_deletes_line_item(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """Soft deletes line item."""
        from core.models import LineItemCreate

        line_item = line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            total_price_cents=5000
        ))

        result = line_item_service.delete(line_item.id)
        assert result is True

        # Should no longer be returned by get_by_id
        fetched = line_item_service.get_by_id(line_item.id)
        assert fetched is None

    def test_returns_false_for_missing(self, db, as_test_user, line_item_service):
        """Returns False when deleting non-existent line item."""
        result = line_item_service.delete(uuid4())
        assert result is False


class TestLineItemList:
    """Tests for LineItemService.list_for_ticket."""

    def test_lists_ticket_line_items(self, db, as_test_user, line_item_service, test_ticket, test_service, catalog_service):
        """Lists all line items for a ticket."""
        from core.models import LineItemCreate, ServiceCreate, PricingType

        # Create a second service
        service2 = catalog_service.create(ServiceCreate(
            name="Screen Repair",
            pricing_type=PricingType.PER_UNIT,
            unit_price_cents=500,
            unit_label="screen"
        ))

        line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            total_price_cents=5000
        ))
        line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=service2.id,
            quantity=4,
            unit_price_cents=500
        ))

        items = line_item_service.list_for_ticket(test_ticket.id)

        assert len(items) == 2
        assert all(item.ticket_id == test_ticket.id for item in items)

        # Cleanup
        catalog_service.delete(service2.id)

    def test_excludes_deleted_items(self, db, as_test_user, line_item_service, test_ticket, test_service):
        """list_for_ticket excludes soft-deleted items."""
        from core.models import LineItemCreate

        item1 = line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            total_price_cents=5000
        ))
        item2 = line_item_service.create(test_ticket.id, LineItemCreate(
            service_id=test_service.id,
            total_price_cents=3000
        ))

        line_item_service.delete(item1.id)

        items = line_item_service.list_for_ticket(test_ticket.id)

        assert len(items) == 1
        assert items[0].id == item2.id
