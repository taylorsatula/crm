"""Tests for domain event models."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from uuid import uuid4, UUID
from datetime import timedelta

import pytest

from core.events import (
    CRMEvent,
    TicketEvent, TicketCreated, TicketClockIn, TicketCompleted, TicketCancelled,
    InvoiceEvent, InvoiceSent, InvoicePaid,
    CustomerEvent, CustomerCreated,
    NoteEvent, NoteCreated,
)
from core.models import (
    Ticket, TicketStatus, ConfirmationStatus,
    Invoice, InvoiceStatus,
    Customer,
    Note,
)
from utils.timezone import now_utc


# =============================================================================
# FIXTURES — lightweight in-memory stubs, no DB needed
# =============================================================================


@pytest.fixture
def _customer():
    now = now_utc()
    return Customer(
        id=uuid4(), user_id=uuid4(),
        first_name="Test", last_name="Customer",
        business_name=None, email=None, phone=None,
        address=None, reference_id=None, notes=None,
        preferred_contact_method=None, preferred_time_of_day=None,
        referred_by=None, stripe_customer_id=None,
        created_at=now, updated_at=now, deleted_at=None,
    )


@pytest.fixture
def _ticket(_customer):
    now = now_utc()
    return Ticket(
        id=uuid4(), user_id=_customer.user_id,
        customer_id=_customer.id, address_id=uuid4(),
        status=TicketStatus.SCHEDULED,
        scheduled_at=now + timedelta(hours=1),
        scheduled_duration_minutes=60,
        confirmation_status=ConfirmationStatus.PENDING,
        confirmation_sent_at=None, confirmed_at=None,
        clock_in_at=None, clock_out_at=None,
        actual_duration_minutes=None,
        notes=None, closed_at=None, is_price_estimated=False,
        created_at=now, updated_at=now, deleted_at=None,
    )


@pytest.fixture
def _invoice(_customer, _ticket):
    now = now_utc()
    return Invoice(
        id=uuid4(), user_id=_customer.user_id,
        customer_id=_customer.id, ticket_id=_ticket.id,
        invoice_number="INV-20250101-0001",
        status=InvoiceStatus.DRAFT,
        subtotal_cents=10000, tax_rate_bps=0,
        tax_amount_cents=0, total_amount_cents=10000,
        amount_paid_cents=0,
        issued_at=None, due_at=None, sent_at=None,
        paid_at=None, voided_at=None,
        stripe_checkout_session_id=None, stripe_payment_intent_id=None,
        notes=None, created_at=now, updated_at=now, deleted_at=None,
    )


@pytest.fixture
def _note(_customer):
    now = now_utc()
    return Note(
        id=uuid4(), user_id=_customer.user_id,
        customer_id=_customer.id, ticket_id=None,
        content="Elderly woman, dog named Biscuit",
        processed_at=None, created_at=now, deleted_at=None,
    )


# =============================================================================
# CONSTRUCTION VIA .create() FACTORY
# =============================================================================


class TestTicketEventFactory:

    def test_ticket_created_stores_ticket_by_identity(self, _ticket, as_test_user):
        event = TicketCreated.create(ticket=_ticket)
        assert event.ticket is _ticket

    def test_ticket_clock_in_stores_ticket_by_identity(self, _ticket, as_test_user):
        event = TicketClockIn.create(ticket=_ticket)
        assert event.ticket is _ticket

    def test_ticket_completed_stores_ticket_by_identity(self, _ticket, as_test_user):
        event = TicketCompleted.create(ticket=_ticket)
        assert event.ticket is _ticket

    def test_ticket_cancelled_stores_ticket_by_identity(self, _ticket, as_test_user):
        event = TicketCancelled.create(ticket=_ticket)
        assert event.ticket is _ticket


class TestInvoiceEventFactory:

    def test_invoice_sent_stores_invoice_by_identity(self, _invoice, as_test_user):
        event = InvoiceSent.create(invoice=_invoice)
        assert event.invoice is _invoice

    def test_invoice_paid_stores_invoice_by_identity(self, _invoice, as_test_user):
        event = InvoicePaid.create(invoice=_invoice)
        assert event.invoice is _invoice


class TestCustomerEventFactory:

    def test_customer_created_stores_customer_by_identity(self, _customer, as_test_user):
        event = CustomerCreated.create(customer=_customer)
        assert event.customer is _customer


class TestNoteEventFactory:

    def test_note_created_stores_note_by_identity(self, _note, as_test_user):
        event = NoteCreated.create(note=_note)
        assert event.note is _note


# =============================================================================
# AUTO-GENERATED METADATA
# =============================================================================


class TestEventId:

    def test_is_valid_uuid4_string(self, _ticket, as_test_user):
        event = TicketCreated.create(ticket=_ticket)
        parsed = UUID(event.event_id, version=4)
        assert str(parsed) == event.event_id

    def test_unique_across_events(self, _ticket, as_test_user):
        ids = {TicketCreated.create(ticket=_ticket).event_id for _ in range(10)}
        assert len(ids) == 10


class TestOccurredAt:

    def test_is_utc_timezone_aware(self, _ticket, as_test_user):
        event = TicketCreated.create(ticket=_ticket)
        assert event.occurred_at.tzinfo == timezone.utc

    def test_bounded_by_wall_clock(self, _ticket, as_test_user):
        before = now_utc()
        event = TicketCreated.create(ticket=_ticket)
        after = now_utc()
        assert before <= event.occurred_at <= after

    def test_all_eight_event_types_generate_utc_occurred_at(
        self, _ticket, _invoice, _customer, _note, as_test_user
    ):
        events = [
            TicketCreated.create(ticket=_ticket),
            TicketClockIn.create(ticket=_ticket),
            TicketCompleted.create(ticket=_ticket),
            TicketCancelled.create(ticket=_ticket),
            InvoiceSent.create(invoice=_invoice),
            InvoicePaid.create(invoice=_invoice),
            CustomerCreated.create(customer=_customer),
            NoteCreated.create(note=_note),
        ]
        for event in events:
            assert event.occurred_at.tzinfo == timezone.utc, (
                f"{type(event).__name__}.occurred_at.tzinfo is {event.occurred_at.tzinfo!r}, expected UTC"
            )
            UUID(event.event_id, version=4)  # valid UUID4


# =============================================================================
# IMMUTABILITY
# =============================================================================


class TestFrozenFields:

    def test_cannot_reassign_ticket(self, _ticket, as_test_user):
        event = TicketCreated.create(ticket=_ticket)
        with pytest.raises(FrozenInstanceError):
            event.ticket = None

    def test_cannot_reassign_invoice(self, _invoice, as_test_user):
        event = InvoiceSent.create(invoice=_invoice)
        with pytest.raises(FrozenInstanceError):
            event.invoice = None

    def test_cannot_reassign_customer(self, _customer, as_test_user):
        event = CustomerCreated.create(customer=_customer)
        with pytest.raises(FrozenInstanceError):
            event.customer = None

    def test_cannot_reassign_note(self, _note, as_test_user):
        event = NoteCreated.create(note=_note)
        with pytest.raises(FrozenInstanceError):
            event.note = None

    def test_cannot_reassign_event_id(self, _ticket, as_test_user):
        event = TicketCreated.create(ticket=_ticket)
        with pytest.raises(FrozenInstanceError):
            event.event_id = "tampered"

    def test_cannot_reassign_occurred_at(self, _ticket, as_test_user):
        event = TicketCreated.create(ticket=_ticket)
        with pytest.raises(FrozenInstanceError):
            event.occurred_at = datetime(2020, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# INHERITANCE HIERARCHY
# =============================================================================


class TestInheritance:

    def test_ticket_events_inherit_from_ticket_event_and_crm_event(self, _ticket, as_test_user):
        for cls in [TicketCreated, TicketClockIn, TicketCompleted, TicketCancelled]:
            event = cls.create(ticket=_ticket)
            assert isinstance(event, TicketEvent)
            assert isinstance(event, CRMEvent)
            assert not isinstance(event, InvoiceEvent)
            assert not isinstance(event, CustomerEvent)
            assert not isinstance(event, NoteEvent)

    def test_invoice_events_inherit_from_invoice_event_and_crm_event(self, _invoice, as_test_user):
        for cls in [InvoiceSent, InvoicePaid]:
            event = cls.create(invoice=_invoice)
            assert isinstance(event, InvoiceEvent)
            assert isinstance(event, CRMEvent)
            assert not isinstance(event, TicketEvent)

    def test_customer_created_inherits_from_customer_event_and_crm_event(self, _customer, as_test_user):
        event = CustomerCreated.create(customer=_customer)
        assert isinstance(event, CustomerEvent)
        assert isinstance(event, CRMEvent)
        assert not isinstance(event, TicketEvent)

    def test_note_created_inherits_from_note_event_and_crm_event(self, _note, as_test_user):
        event = NoteCreated.create(note=_note)
        assert isinstance(event, NoteEvent)
        assert isinstance(event, CRMEvent)
        assert not isinstance(event, TicketEvent)
