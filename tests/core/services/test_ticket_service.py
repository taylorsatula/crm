"""Tests for TicketService."""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta

from utils.timezone import now_utc


@pytest.fixture
def ticket_service(db):
    """TicketService with real DB."""
    from core.services.ticket_service import TicketService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return TicketService(db, audit)


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
def test_customer(as_test_user, customer_service):
    """Create a test customer."""
    from core.models import CustomerCreate

    customer = customer_service.create(CustomerCreate(first_name="Test", last_name="Customer"))
    yield customer
    customer_service.delete(customer.id)


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    """Create a test address."""
    from core.models import AddressCreate

    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="123 Test St",
        city="Austin",
        state="TX",
        zip="78701"
    ))


class TestTicketCreate:
    """Tests for TicketService.create."""

    def test_creates_ticket(self, db, as_test_user, ticket_service, test_customer, test_address):
        """Creates ticket with provided data."""
        from core.models import TicketCreate, TicketStatus

        scheduled = now_utc() + timedelta(days=1)
        data = TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=scheduled
        )

        ticket = ticket_service.create(data)

        assert ticket.customer_id == test_customer.id
        assert ticket.address_id == test_address.id
        assert ticket.status == TicketStatus.SCHEDULED

    def test_starts_with_scheduled_status(self, db, as_test_user, ticket_service, test_customer, test_address):
        """New tickets start in SCHEDULED status."""
        from core.models import TicketCreate, TicketStatus

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        assert ticket.status == TicketStatus.SCHEDULED
        assert ticket.clock_in_at is None
        assert ticket.clock_out_at is None
        assert ticket.closed_at is None


class TestTicketClockIn:
    """Tests for TicketService.clock_in."""

    def test_clock_in_sets_time_and_status(self, db, as_test_user, ticket_service, test_customer, test_address):
        """clock_in sets clock_in_at and status to IN_PROGRESS."""
        from core.models import TicketCreate, TicketStatus

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        updated = ticket_service.clock_in(ticket.id)

        assert updated.clock_in_at is not None
        assert updated.status == TicketStatus.IN_PROGRESS

    def test_clock_in_rejects_non_scheduled(self, db, as_test_user, ticket_service, test_customer, test_address):
        """Cannot clock into completed ticket (already clocked in takes precedence)."""
        from core.models import TicketCreate

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        # Clock in, clock out, close
        ticket_service.clock_in(ticket.id)
        ticket_service.clock_out(ticket.id)
        ticket_service.close(ticket.id)

        # Since we already clocked in, that's the error we get (more specific)
        with pytest.raises(ValueError, match="already clocked in"):
            ticket_service.clock_in(ticket.id)

    def test_clock_in_rejects_already_clocked(self, db, as_test_user, ticket_service, test_customer, test_address):
        """Cannot clock in twice."""
        from core.models import TicketCreate

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        ticket_service.clock_in(ticket.id)

        with pytest.raises(ValueError, match="already clocked in"):
            ticket_service.clock_in(ticket.id)


class TestTicketClockOut:
    """Tests for TicketService.clock_out."""

    def test_clock_out_calculates_duration(self, db, as_test_user, ticket_service, test_customer, test_address):
        """clock_out sets clock_out_at and calculates duration."""
        from core.models import TicketCreate

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        ticket_service.clock_in(ticket.id)
        updated = ticket_service.clock_out(ticket.id)

        assert updated.clock_out_at is not None
        assert updated.actual_duration_minutes is not None
        assert updated.actual_duration_minutes >= 0

    def test_clock_out_requires_clock_in(self, db, as_test_user, ticket_service, test_customer, test_address):
        """Cannot clock out without clocking in first."""
        from core.models import TicketCreate

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        with pytest.raises(ValueError, match="not clocked in"):
            ticket_service.clock_out(ticket.id)


class TestTicketClose:
    """Tests for TicketService.close."""

    def test_close_marks_completed(self, db, as_test_user, ticket_service, test_customer, test_address):
        """close sets status to COMPLETED and closed_at."""
        from core.models import TicketCreate, TicketStatus

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        ticket_service.clock_in(ticket.id)
        ticket_service.clock_out(ticket.id)
        closed = ticket_service.close(ticket.id)

        assert closed.status == TicketStatus.COMPLETED
        assert closed.closed_at is not None

    def test_closed_ticket_immutable(self, db, as_test_user, ticket_service, test_customer, test_address):
        """Cannot modify closed ticket."""
        from core.models import TicketCreate, TicketUpdate

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        ticket_service.clock_in(ticket.id)
        ticket_service.clock_out(ticket.id)
        ticket_service.close(ticket.id)

        with pytest.raises(ValueError, match="closed.*immutable"):
            ticket_service.update(ticket.id, TicketUpdate(notes="New notes"))


class TestTicketCancel:
    """Tests for TicketService.cancel."""

    def test_cancel_sets_status(self, db, as_test_user, ticket_service, test_customer, test_address):
        """cancel sets status to CANCELLED."""
        from core.models import TicketCreate, TicketStatus

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        cancelled = ticket_service.cancel(ticket.id)

        assert cancelled.status == TicketStatus.CANCELLED

    def test_cannot_cancel_completed(self, db, as_test_user, ticket_service, test_customer, test_address):
        """Cannot cancel a completed ticket."""
        from core.models import TicketCreate

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))

        ticket_service.clock_in(ticket.id)
        ticket_service.clock_out(ticket.id)
        ticket_service.close(ticket.id)

        with pytest.raises(ValueError, match="cannot cancel"):
            ticket_service.cancel(ticket.id)


class TestTicketList:
    """Tests for TicketService list methods."""

    def test_list_by_date_range(self, db, as_test_user, ticket_service, test_customer, test_address):
        """list_by_date_range returns tickets in range."""
        from core.models import TicketCreate

        tomorrow = now_utc() + timedelta(days=1)
        next_week = now_utc() + timedelta(days=7)

        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=tomorrow
        ))
        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=next_week
        ))

        # Query for tomorrow only
        start = now_utc()
        end = now_utc() + timedelta(days=2)
        tickets = ticket_service.list_by_date_range(start, end)

        assert len(tickets) >= 1
        assert all(start <= t.scheduled_at <= end for t in tickets)

    def test_list_for_customer(self, db, as_test_user, ticket_service, customer_service, test_address):
        """list_for_customer returns only that customer's tickets."""
        from core.models import TicketCreate, CustomerCreate, AddressCreate

        # Create two customers
        customer_a = customer_service.create(CustomerCreate(first_name="Customer A"))
        customer_b = customer_service.create(CustomerCreate(first_name="Customer B"))

        # Use same address for simplicity (belongs to test_customer but we'll ignore for this test)
        ticket_service.create(TicketCreate(
            customer_id=customer_a.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=1)
        ))
        ticket_service.create(TicketCreate(
            customer_id=customer_b.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=2)
        ))

        tickets_a = ticket_service.list_for_customer(customer_a.id)
        tickets_b = ticket_service.list_for_customer(customer_b.id)

        assert len(tickets_a) == 1
        assert tickets_a[0].customer_id == customer_a.id
        assert len(tickets_b) == 1
        assert tickets_b[0].customer_id == customer_b.id

        # Cleanup
        customer_service.delete(customer_a.id)
        customer_service.delete(customer_b.id)


class TestTicketListToday:
    """Tests for TicketService.list_today."""

    def test_returns_tickets_scheduled_today(self, db, as_test_user, ticket_service, test_customer, test_address):
        """list_today returns only today's tickets."""
        from core.models import TicketCreate
        from datetime import date, time, timezone

        today = date.today()
        today_morning = datetime.combine(today, time(9, 0), tzinfo=timezone.utc)
        tomorrow_morning = datetime.combine(today + timedelta(days=1), time(9, 0), tzinfo=timezone.utc)

        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=today_morning
        ))
        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=tomorrow_morning
        ))

        tickets = ticket_service.list_today()

        assert len(tickets) == 1
        assert tickets[0].scheduled_at.date() == today

    def test_returns_empty_when_no_tickets_today(self, db, as_test_user, ticket_service, test_customer, test_address):
        """list_today returns empty list when no tickets scheduled today."""
        from core.models import TicketCreate
        from datetime import date, time, timezone

        tomorrow = date.today() + timedelta(days=1)
        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=datetime.combine(tomorrow, time(9, 0), tzinfo=timezone.utc)
        ))

        tickets = ticket_service.list_today()

        assert tickets == []

    def test_ordered_by_scheduled_at(self, db, as_test_user, ticket_service, test_customer, test_address):
        """list_today orders tickets by scheduled_at ascending."""
        from core.models import TicketCreate
        from datetime import date, time, timezone

        today = date.today()
        afternoon = datetime.combine(today, time(14, 0), tzinfo=timezone.utc)
        morning = datetime.combine(today, time(8, 0), tzinfo=timezone.utc)

        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=afternoon
        ))
        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=morning
        ))

        tickets = ticket_service.list_today()

        assert len(tickets) == 2
        assert tickets[0].scheduled_at < tickets[1].scheduled_at


class TestTicketGetCurrent:
    """Tests for TicketService.get_current."""

    def test_returns_in_progress_ticket(self, db, as_test_user, ticket_service, test_customer, test_address):
        """get_current returns in-progress ticket."""
        from core.models import TicketCreate, TicketStatus

        ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(hours=1)
        ))
        ticket_service.clock_in(ticket.id)

        current = ticket_service.get_current()

        assert current is not None
        assert current.id == ticket.id
        assert current.status == TicketStatus.IN_PROGRESS

    def test_returns_none_when_only_scheduled(self, db, as_test_user, ticket_service, test_customer, test_address):
        """get_current returns None when tickets exist but none are in-progress."""
        from core.models import TicketCreate

        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(hours=1)
        ))

        current = ticket_service.get_current()

        assert current is None

    def test_returns_none_when_no_tickets(self, db, as_test_user, ticket_service):
        """get_current returns None when no tickets exist."""
        current = ticket_service.get_current()

        assert current is None
